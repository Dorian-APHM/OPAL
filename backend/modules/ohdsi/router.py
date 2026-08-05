"""
OHDSI Quality Tools integration.

The backend no longer touches Docker. It is a thin client of the dedicated
``opal-ohdsi-runner`` service (see ohdsi-tools/runner), which executes the R
tools as subprocesses and exposes a small internal HTTP API. This router:

- gates everything behind OHDSI_MODE (on/off),
- enforces per-CDM access on launch AND on reads (logs/status/files),
- relays the runner's job state, logs (SSE) and output files,
- keeps the frontend's service-keyed contract by resolving each service to its
  most recent job that the caller is allowed to see.
"""
import json
import logging
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import (
    AUTH_ENABLED,
    OHDSI_ENABLED,
    OHDSI_RUNNER_TOKEN,
    OHDSI_RUNNER_URL,
)
from db.app_db import get_db
from db.models import CdmConfig, AnalysisSettings
from utils.cdm_helper import build_schema_map
from utils.cdm_helper import check_cdm_access
from utils.crypto import decrypt_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ohdsi", tags=["ohdsi"])

SERVICES = {"achilles", "achilles-export", "dqd", "cdmonboarding", "dashboardexport"}
_RUNNER_TIMEOUT = httpx.Timeout(10.0)


class RunRequest(BaseModel):
    cdm_name: str
    results_schema: str = Field(default="omop_cdm", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    vocabulary_schema: str = Field(default="omop_cdm", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    cdm_version: str = Field(default="5.4", pattern=r"^[0-9]+\.[0-9]+$")
    cdm_source_name: str = ""


# ---------------------------------------------------------------------------
# Runner client helpers
# ---------------------------------------------------------------------------
def _require_enabled() -> None:
    if not OHDSI_ENABLED:
        raise HTTPException(status_code=503, detail="OHDSI is disabled (set OHDSI_MODE=on)")


def _runner(method: str, path: str, **kwargs) -> httpx.Response:
    """Call the runner with the shared token. Raises 502 on connection error."""
    headers = {"X-Runner-Token": OHDSI_RUNNER_TOKEN}
    try:
        with httpx.Client(timeout=_RUNNER_TIMEOUT) as client:
            return client.request(method, f"{OHDSI_RUNNER_URL}{path}", headers=headers, **kwargs)
    except httpx.HTTPError as exc:
        logger.warning("OHDSI runner unreachable: %s", exc)
        raise HTTPException(status_code=502, detail="OHDSI runner unreachable") from exc


def _can_access(request: Request, cdm_name: str) -> bool:
    """Whether the caller may see resources for the given CDM (no raise)."""
    if not AUTH_ENABLED:
        return True
    user_info = getattr(request.state, "user", None)
    if not user_info:
        return False
    from auth.keycloak import _check_cdm_access
    return _check_cdm_access(cdm_name, user_info)


def _latest_job_for_service(request: Request, service: str) -> dict | None:
    """Most recent job of a service that the caller is allowed to see."""
    resp = _runner("GET", "/jobs", params={"service": service})
    if resp.status_code != 200:
        return None
    for job in resp.json():  # runner returns newest first
        if _can_access(request, job.get("cdm_name", "")):
            return job
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/config")
def get_config(request: Request) -> dict:
    """Feature flag for the frontend. Always available (even when disabled)."""
    return {"enabled": OHDSI_ENABLED}


@router.post("/run/{service_name}")
def run_service(service_name: str, req: RunRequest, request: Request, db: Session = Depends(get_db)):
    """Launch an OHDSI service for the given CDM via the runner."""
    _require_enabled()
    if service_name not in SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")

    check_cdm_access(request, req.cdm_name)

    cdm = db.query(CdmConfig).filter(CdmConfig.name == req.cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{req.cdm_name}' not found")

    password = decrypt_password(cdm.db_password_encrypted)

    # Resolve the clinical CDM schema the same way the rest of the backend does:
    # analysis-settings override > per-category override > CDM default schema.
    settings = db.query(AnalysisSettings).filter(
        AnalysisSettings.cdm_name == req.cdm_name
    ).first()

    user = getattr(request.state, "user", {}) or {}
    launched_by = user.get("preferred_username", "anonymous")

    payload = {
        "service": service_name,
        "cdm_name": req.cdm_name,
        "db_host": cdm.db_host,
        "db_port": cdm.db_port,
        "db_name": cdm.db_name,
        "db_user": cdm.db_user,
        "db_password": password,
        "cdm_schema": build_schema_map(cdm, settings).schema_for("person"),
        "results_schema": req.results_schema,
        "vocabulary_schema": req.vocabulary_schema,
        "cdm_version": req.cdm_version,
        "cdm_source_name": req.cdm_source_name or req.cdm_name,
        "launched_by": launched_by,
    }
    resp = _runner("POST", "/jobs", json=payload)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=f"Runner error: {resp.text}")
    return {"ok": True, "job_id": resp.json().get("job_id")}


def _assert_stop_allowed(request: Request, job: dict) -> None:
    """403 unless the caller launched the job or is an admin/data-manager."""
    if not AUTH_ENABLED:
        return
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = user.get("preferred_username", "")
    roles = user.get("roles", []) or user.get("realm_access", {}).get("roles", [])
    if username == job.get("launched_by") or any(r in ("admin", "data-manager") for r in roles):
        return
    raise HTTPException(status_code=403, detail="Only the launcher or an admin can stop this service")


@router.post("/stop/{service_name}")
def stop_service(service_name: str, request: Request):
    """Cancel the running job of a service."""
    _require_enabled()
    if service_name not in SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
    job = _latest_job_for_service(request, service_name)
    if not job or job["status"] not in ("running", "queued"):
        raise HTTPException(status_code=400, detail="Nothing to stop")
    _assert_stop_allowed(request, job)
    resp = _runner("POST", f"/jobs/{job['job_id']}/cancel")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=f"Runner error: {resp.text}")
    return {"ok": True}


@router.get("/status")
def get_status(request: Request) -> dict:
    """Latest accessible job status per service."""
    _require_enabled()
    result = {svc: {"status": "idle", "log_count": 0, "cdm_name": "", "job_id": ""} for svc in SERVICES}
    resp = _runner("GET", "/jobs")
    if resp.status_code != 200:
        return result
    seen: set[str] = set()
    for job in resp.json():  # newest first
        svc = job.get("service")
        if svc in result and svc not in seen and _can_access(request, job.get("cdm_name", "")):
            # job_id lets the UI dismiss a specific finished job (see OhdsiPage).
            result[svc] = {
                "status": job["status"],
                "log_count": 0,
                "cdm_name": job.get("cdm_name", ""),
                "job_id": job.get("job_id", ""),
            }
            seen.add(svc)
    return result


@router.get("/logs/{service_name}/history")
def get_log_history(service_name: str, request: Request) -> dict:
    """Full accumulated logs for the latest accessible job of a service."""
    _require_enabled()
    if service_name not in SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
    job = _latest_job_for_service(request, service_name)
    if not job:
        return {"status": "idle", "logs": [], "offset": 0}
    resp = _runner("GET", f"/jobs/{job['job_id']}/logs", params={"offset": 0})
    if resp.status_code != 200:
        return {"status": "idle", "logs": [], "offset": 0}
    data = resp.json()
    return {"status": data["status"], "logs": data["lines"], "offset": data["offset"]}


@router.get("/logs/{service_name}")
def stream_logs(service_name: str, request: Request, offset: int = Query(0)):
    """SSE relay of the runner job logs. Authenticated via SSE ticket (middleware)."""
    _require_enabled()
    if service_name not in SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
    job = _latest_job_for_service(request, service_name)

    def generate():
        if not job:
            yield f"data: {json.dumps({'status': 'idle', 'lines': [], 'offset': 0})}\n\n"
            return
        job_id = job["job_id"]
        last = offset
        while True:
            try:
                resp = _runner("GET", f"/jobs/{job_id}/logs", params={"offset": last})
            except HTTPException:
                yield f"data: {json.dumps({'status': 'error', 'lines': ['runner unreachable'], 'offset': last})}\n\n"
                return
            if resp.status_code != 200:
                yield f"data: {json.dumps({'status': 'error', 'lines': [], 'offset': last})}\n\n"
                return
            data = resp.json()
            status = data["status"]
            new_lines = data["lines"]
            last = data["offset"]
            if new_lines:
                yield f"data: {json.dumps({'status': status, 'lines': new_lines, 'offset': last})}\n\n"
            if status in ("done", "error", "cancelled"):
                yield f"data: {json.dumps({'status': status, 'lines': [], 'offset': last})}\n\n"
                return
            time.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/files/{path:path}")
@router.get("/files/")
def list_or_download_files(request: Request, path: str = ""):
    """Browse/download runner output files. Per-CDM access enforced on the first segment."""
    _require_enabled()
    # Output layout is <cdm_name>/<service>/...; gate on the CDM segment.
    first_segment = path.split("/", 1)[0] if path else ""
    if first_segment and not _can_access(request, first_segment):
        raise HTTPException(status_code=403, detail=f"Access denied to CDM '{first_segment}'")

    resp = _runner("GET", f"/files/{path}")
    if resp.status_code == 403:
        raise HTTPException(status_code=403, detail="Access denied")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Runner error")

    content_type = resp.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        return resp.json()
    # Binary/file download — pass through with the runner's headers.
    headers = {}
    if "content-disposition" in resp.headers:
        headers["content-disposition"] = resp.headers["content-disposition"]
    return Response(content=resp.content, media_type=content_type or "application/octet-stream", headers=headers)
