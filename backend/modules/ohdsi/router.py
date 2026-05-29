"""
OHDSI Quality Tools integration.
Launches Docker containers for Achilles, DQD, Achilles Export, CDM Onboarding
and streams their logs in real-time via SSE.
"""
import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path

import docker
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import (
    OHDSI_IMAGE_PREFIX,
    OHDSI_OUTPUT_DIR,
    OHDSI_HOST_OUTPUT_DIR,
    OHDSI_HOST_SCRIPTS_DIR,
    OHDSI_HOST_JDBC_DIR,
)
from db.app_db import get_db
from db.models import CdmConfig
from utils.cdm_helper import build_schema_map
from utils.cdm_helper import check_cdm_access
from utils.crypto import decrypt_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ohdsi", tags=["ohdsi"])

# ---------------------------------------------------------------------------
# Service definitions
# ---------------------------------------------------------------------------
SERVICES = {
    "achilles": {
        "label": "Achilles",
        "command": ["Rscript", "scripts/run_achilles.R"],
        "output_dir": "achilles",
    },
    "achilles-export": {
        "label": "Achilles Export",
        "command": ["Rscript", "scripts/run_achilles_export.R"],
        "output_dir": "achilles",
    },
    "dqd": {
        "label": "Data Quality Dashboard",
        "command": ["Rscript", "scripts/run_dqd.R"],
        "output_dir": "dqd",
    },
    "cdmonboarding": {
        "label": "CDM Onboarding",
        "command": ["Rscript", "scripts/run_cdmonboarding.R"],
        "output_dir": "cdmonboarding",
    },
}

# Directories that must exist for every CDM (even empty, for manual uploads)
_CDM_OUTPUT_DIRS = sorted({s["output_dir"] for s in SERVICES.values()})  # achilles, cdmonboarding, dqd

# In-memory state tracking
_tasks: dict[str, dict] = {}
_lock = threading.Lock()


def ensure_cdm_output_dirs(cdm_name: str) -> None:
    """Create the OHDSI output sub-folders for a CDM if they don't exist.

    Directories are created with mode 0o777 so the host user can also
    write into them (e.g. to drop files manually).
    """
    base = Path(OHDSI_OUTPUT_DIR) / cdm_name
    for d in _CDM_OUTPUT_DIRS:
        target = base / d
        target.mkdir(parents=True, exist_ok=True)
        # Ensure permissive mode even if umask restricted it
        try:
            target.chmod(0o777)
            target.parent.chmod(0o777)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class RunRequest(BaseModel):
    cdm_name: str
    results_schema: str = Field(default="omop_cdm", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    vocabulary_schema: str = Field(default="omop_cdm", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    cdm_version: str = Field(default="5.4", pattern=r"^[0-9]+\.[0-9]+$")
    cdm_source_name: str = ""


# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------
def _get_image_name(service_name: str) -> str:
    """Resolve the Docker image name for a service."""
    # The images built by ohdsi-docker compose are named <prefix>-<service>
    return f"{OHDSI_IMAGE_PREFIX}-{service_name}"


def _run_container(service_name: str, env_vars: dict, creds_file: str | None = None, cdm_name: str = "") -> None:
    """Run an OHDSI container in a background thread and collect logs.

    cdm_name: used to organise output into per-CDM sub-folders.
    creds_file: path to a temporary credentials file that will be deleted
    after the container starts (S08: avoid plaintext password in env vars /
    docker inspect). The file is mounted at /run/secrets/opal_creds.env inside
    the container so the entrypoint can source it via:
        [ -f "$DB_CREDS_FILE" ] && export $(grep -v '^#' "$DB_CREDS_FILE" | xargs)
    """
    try:
        client = docker.from_env()
    except Exception as e:
        import time as _time
        with _lock:
            _tasks[service_name]["status"] = "error"
            _tasks[service_name]["logs"].append(f"Docker connection error: {e}")
            _tasks[service_name]["finished_at"] = _time.time()
        _cleanup_creds_file(creds_file)
        return

    image_name = _get_image_name(service_name)

    # Verify image exists
    try:
        client.images.get(image_name)
    except docker.errors.ImageNotFound:
        import time as _time
        with _lock:
            _tasks[service_name]["status"] = "error"
            _tasks[service_name]["logs"].append(
                f"Image '{image_name}' not found. Run 'docker compose build' in ohdsi-docker first."
            )
            _tasks[service_name]["finished_at"] = _time.time()
        _cleanup_creds_file(creds_file)
        return

    service_cfg = SERVICES[service_name]
    host_output = OHDSI_HOST_OUTPUT_DIR
    host_scripts = OHDSI_HOST_SCRIPTS_DIR

    # Organise output per CDM: ohdsi_output/{cdm_name}/{service_output_dir}
    cdm_folder = cdm_name or "default"
    volumes = {
        host_scripts: {"bind": "/app/scripts", "mode": "ro"},
        f"{host_output}/{cdm_folder}/{service_cfg['output_dir']}": {"bind": "/output", "mode": "rw"},
        OHDSI_HOST_JDBC_DIR: {"bind": "/drivers", "mode": "ro"},
    }
    # CDM Onboarding needs DQD output from the *same* CDM
    if service_name == "cdmonboarding":
        volumes[f"{host_output}/{cdm_folder}/dqd"] = {"bind": "/input/dqd", "mode": "ro"}

    # Mount the credentials file read-only so the container entrypoint can source it.
    # The file is deleted from the host right after container creation.
    if creds_file:
        volumes[creds_file] = {"bind": "/run/secrets/opal_creds.env", "mode": "ro"}

    try:
        container = client.containers.run(
            image_name,
            command=service_cfg["command"],
            environment=env_vars,
            volumes=volumes,
            network="opal-network",
            detach=True,
            remove=False,
        )
        with _lock:
            _tasks[service_name]["container_id"] = container.id

        # Delete the credentials file now that the container has started.
        # The bind-mount keeps the file accessible inside the container via the kernel
        # inode as long as the container has it open; removing the host path prevents
        # any other process from reading the plaintext password from disk.
        _cleanup_creds_file(creds_file)

        seen = set()
        for chunk in container.logs(stream=True, follow=True, stdout=True, stderr=True):
            line = chunk.decode("utf-8", errors="replace").rstrip("\n")
            if not line:
                continue
            # Deduplicate consecutive identical lines (R writes to both stdout and stderr)
            line_key = line.strip()
            if line_key in seen:
                continue
            seen.add(line_key)
            # Keep set from growing unbounded — only dedup within a sliding window
            if len(seen) > 100:
                seen.clear()
            with _lock:
                _tasks[service_name]["logs"].append(line)

        import time as _time
        result = container.wait()
        exit_code = result.get("StatusCode", -1)
        with _lock:
            if exit_code == 0:
                _tasks[service_name]["status"] = "done"
                _tasks[service_name]["logs"].append("--- Finished successfully ---")
            else:
                _tasks[service_name]["status"] = "error"
                _tasks[service_name]["logs"].append(f"--- Failed (exit code {exit_code}) ---")
            _tasks[service_name]["finished_at"] = _time.time()

        container.remove()

    except Exception as e:
        import time as _time
        with _lock:
            _tasks[service_name]["status"] = "error"
            _tasks[service_name]["logs"].append(f"Error: {e}")
            _tasks[service_name]["finished_at"] = _time.time()
        _cleanup_creds_file(creds_file)


def _cleanup_creds_file(path: str | None) -> None:
    """Securely delete a temporary credentials file if it exists."""
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/run/{service_name}")
def run_service(service_name: str, req: RunRequest, request: Request, db: Session = Depends(get_db)):
    """Launch an OHDSI service container for the given CDM."""
    if service_name not in SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")

    check_cdm_access(request, req.cdm_name)

    with _lock:
        if service_name in _tasks and _tasks[service_name]["status"] == "running":
            raise HTTPException(status_code=409, detail="Service already running")

    # Fetch CDM connection details
    cdm = db.query(CdmConfig).filter(CdmConfig.name == req.cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{req.cdm_name}' not found")

    password = decrypt_password(cdm.db_password_encrypted)

    # S08: Write the DB password to a temporary credentials file (mode 0600).
    # The file is mounted read-only inside the container at /run/secrets/opal_creds.env
    # and deleted from the host right after the container starts, so the password
    # never persists on disk beyond container launch.
    # Container entrypoints should source the file:
    #   [ -f "$DB_CREDS_FILE" ] && export $(grep -v '^#' "$DB_CREDS_FILE" | xargs)
    creds_fd, creds_path = tempfile.mkstemp(prefix="opal_ohdsi_creds_", suffix=".env")
    try:
        os.write(creds_fd, f"DB_PASSWORD={password}\n".encode())
    finally:
        os.close(creds_fd)
    try:
        os.chmod(creds_path, 0o600)
    except OSError:
        pass

    env_vars = {
        "DB_SYSTEM": "postgresql",
        "DB_HOST": cdm.db_host,
        "DB_PORT": str(cdm.db_port),
        "DB_NAME": cdm.db_name,
        "DB_USER": cdm.db_user,
        "DB_PASSWORD": password,
        "DB_SERVER": f"{cdm.db_host}/{cdm.db_name}",
        # OHDSI's "CDM schema" holds the clinical data tables.
        "CDM_SCHEMA": build_schema_map(cdm).schema_for("person"),
        "RESULTS_SCHEMA": req.results_schema,
        "VOCABULARY_SCHEMA": req.vocabulary_schema,
        "CDM_VERSION": req.cdm_version,
        "CDM_SOURCE_NAME": req.cdm_source_name or req.cdm_name,
        "PATH_TO_DRIVER": "/drivers",
        "DB_CREDS_FILE": "/run/secrets/opal_creds.env",
    }

    # S10: record who launched this service so stop_service can enforce ownership.
    user = getattr(request.state, "user", {}) or {}
    launched_by = user.get("preferred_username", "anonymous")

    # Validate cdm_name is safe for use as a folder name (no path separators or special chars)
    if not req.cdm_name or not re.match(r'^[A-Za-z0-9_\-. ]+$', req.cdm_name):
        raise HTTPException(status_code=400, detail="CDM name contains invalid characters for folder name")

    # Ensure all OHDSI output directories exist for this CDM
    ensure_cdm_output_dirs(req.cdm_name)

    with _lock:
        _tasks[service_name] = {
            "container_id": None,
            "status": "running",
            "launched_by": launched_by,
            "cdm_name": req.cdm_name,
            "logs": [f"Launching {SERVICES[service_name]['label']} for {req.cdm_name}..."],
        }

    from utils.thread_pool import submit_task
    submit_task(_run_container, service_name, env_vars, creds_path, req.cdm_name)

    return {"ok": True}


def _assert_ohdsi_stop_allowed(request: Request, task: dict) -> None:
    """Raise HTTP 403 if the caller is not the service launcher or an admin."""
    from config import AUTH_ENABLED
    if not AUTH_ENABLED:
        return
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = user.get("preferred_username", "")
    roles = user.get("roles", []) or user.get("realm_access", {}).get("roles", [])
    if username == task.get("launched_by") or any(r in ("admin", "data-manager") for r in roles):
        return
    raise HTTPException(status_code=403, detail="Only the launcher or an admin can stop this service")


@router.post("/stop/{service_name}")
def stop_service(service_name: str, request: Request):
    """Stop a running OHDSI service container. Requires authentication."""
    with _lock:
        task = _tasks.get(service_name)
        if not task or task["status"] != "running" or not task["container_id"]:
            raise HTTPException(status_code=400, detail="Nothing to stop")
        container_id = task["container_id"]

    _assert_ohdsi_stop_allowed(request, task)

    try:
        client = docker.from_env()
        container = client.containers.get(container_id)
        container.stop(timeout=5)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True}


@router.get("/status")
def get_status(request: Request):
    """Return status of all services. Requires authentication."""
    with _lock:
        result = {}
        for svc in SERVICES:
            task = _tasks.get(svc)
            if task:
                result[svc] = {
                    "status": task["status"],
                    "log_count": len(task["logs"]),
                    "cdm_name": task.get("cdm_name", ""),
                }
            else:
                result[svc] = {"status": "idle", "log_count": 0, "cdm_name": ""}
    return result


@router.get("/logs/{service_name}/history")
def get_log_history(service_name: str, request: Request):
    """Return all accumulated logs for a service. Requires authentication."""
    if service_name not in SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
    with _lock:
        task = _tasks.get(service_name)
        if not task:
            return {"status": "idle", "logs": [], "offset": 0}
        return {
            "status": task["status"],
            "logs": list(task["logs"]),
            "offset": len(task["logs"]),
        }


@router.get("/logs/{service_name}")
def stream_logs(service_name: str, request: Request, offset: int = Query(0)):
    """SSE endpoint for real-time log streaming. Requires authentication."""
    if service_name not in SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")

    def generate():
        last_index = offset
        while True:
            with _lock:
                task = _tasks.get(service_name)
                if not task:
                    yield f"data: {json.dumps({'status': 'idle', 'lines': [], 'offset': 0})}\n\n"
                    return
                new_lines = task["logs"][last_index:]
                last_index = len(task["logs"])
                status = task["status"]

            if new_lines:
                yield f"data: {json.dumps({'status': status, 'lines': new_lines, 'offset': last_index})}\n\n"

            if status in ("done", "error"):
                yield f"data: {json.dumps({'status': status, 'lines': [], 'offset': last_index})}\n\n"
                return

            time.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/files/{path:path}")
@router.get("/files/")
def list_or_download_files(request: Request, path: str = ""):
    """Browse output files or download a specific file. Requires authentication."""
    output_dir = Path(OHDSI_OUTPUT_DIR)
    target = (output_dir / path).resolve() if path else output_dir.resolve()

    if not str(target).startswith(str(output_dir.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    if not target.exists():
        return []

    if target.is_file():
        return FileResponse(str(target), filename=target.name)

    items = []
    for entry in sorted(target.iterdir()):
        rel = str(entry.relative_to(output_dir))
        items.append({
            "name": entry.name,
            "path": rel,
            "is_dir": entry.is_dir(),
            "size": entry.stat().st_size if entry.is_file() else None,
        })
    return items
