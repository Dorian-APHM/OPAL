"""
OPAL OHDSI Runner — minimal job API.

Runs the OHDSI R tools (Achilles, Achilles Export, DQD, CDM Onboarding) as
*subprocesses* of this service. There is NO Docker socket and NO container
orchestration: the OPAL backend calls this internal HTTP API, which spawns
`Rscript scripts/run_<service>.R` with the per-job environment.

Security model: a shared bearer token (OHDSI_RUNNER_TOKEN) gates every route.
The service is meant to live on an internal network reachable only by the
backend, with egress limited to the external OMOP database.

Job state is persisted in SQLite so it survives restarts and supports
concurrent runs across CDMs. On startup, jobs left "running"/"queued" by a
previous process are reconciled to "error" (their subprocesses died with the
runner).
"""
import os
import re
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_ROOT = os.getenv("OHDSI_APP_ROOT", "/app")           # holds scripts/, drivers/
DATA_DIR = Path(os.getenv("OHDSI_DATA_DIR", "/data"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(DATA_DIR / "output")))
LOGS_DIR = Path(os.getenv("OHDSI_LOGS_DIR", str(DATA_DIR / "logs")))
JOBS_DB = os.getenv("OHDSI_JOBS_DB", str(DATA_DIR / "jobs.db"))
PATH_TO_DRIVER = os.getenv("PATH_TO_DRIVER", str(Path(APP_ROOT) / "drivers"))
RUNNER_TOKEN = os.getenv("OHDSI_RUNNER_TOKEN", "")
MAX_CONCURRENT = int(os.getenv("OHDSI_MAX_CONCURRENT_JOBS", "2"))

for _d in (OUTPUT_DIR, LOGS_DIR, Path(JOBS_DB).parent):
    _d.mkdir(parents=True, exist_ok=True)

# service -> (relative Rscript path, output sub-folder)
SERVICES: dict[str, tuple[str, str]] = {
    "achilles": ("scripts/run_achilles.R", "achilles"),
    "achilles-export": ("scripts/run_achilles_export.R", "achilles"),
    "dqd": ("scripts/run_dqd.R", "dqd"),
    "cdmonboarding": ("scripts/run_cdmonboarding.R", "cdmonboarding"),
}

_CDM_NAME_RE = re.compile(r"^[A-Za-z0-9_\-. ]+$")

# ---------------------------------------------------------------------------
# Persistence (SQLite)
# ---------------------------------------------------------------------------
_db_lock = threading.Lock()
_conn = sqlite3.connect(JOBS_DB, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.execute(
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id          TEXT PRIMARY KEY,
        service     TEXT NOT NULL,
        cdm_name    TEXT NOT NULL,
        status      TEXT NOT NULL,
        launched_by TEXT,
        created_at  REAL NOT NULL,
        finished_at REAL,
        output_dir  TEXT NOT NULL,
        log_path    TEXT NOT NULL
    )
    """
)
_conn.commit()


def _db(query: str, params: tuple = (), *, commit: bool = False):
    with _db_lock:
        cur = _conn.execute(query, params)
        if commit:
            _conn.commit()
        return cur


def _job_row(job_id: str):
    cur = _db("SELECT * FROM jobs WHERE id = ?", (job_id,))
    return cur.fetchone()


def _set_status(job_id: str, status: str, *, finished: bool = False) -> None:
    if finished:
        _db("UPDATE jobs SET status = ?, finished_at = ? WHERE id = ?",
            (status, time.time(), job_id), commit=True)
    else:
        _db("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id), commit=True)


# Reconcile jobs interrupted by a previous runner process.
_db("UPDATE jobs SET status = 'error', finished_at = COALESCE(finished_at, ?) "
    "WHERE status IN ('running', 'queued')", (time.time(),), commit=True)

# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT, thread_name_prefix="ohdsi-job")
_procs: dict[str, subprocess.Popen] = {}
_procs_lock = threading.Lock()


def _append_log(log_path: str, line: str) -> None:
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(line.rstrip("\n") + "\n")


# Binary used to run the R scripts. Overridable for tests/simulation.
RSCRIPT_BIN = os.getenv("OHDSI_RSCRIPT_BIN", "Rscript")


def _build_cmd(service: str) -> list[str]:
    script_rel, _ = SERVICES[service]
    return [RSCRIPT_BIN, script_rel]


def _run_job(job_id: str, service: str, env: dict, log_path: str) -> None:
    _set_status(job_id, "running")
    full_env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
    full_env.update(env)
    # Keep R/Java scratch inside a writable (tmpfs) location for read-only rootfs.
    full_env.setdefault("HOME", "/tmp")
    full_env.setdefault("TMPDIR", "/tmp")
    try:
        proc = subprocess.Popen(
            _build_cmd(service),
            cwd=APP_ROOT,
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,  # own process group, so cancel kills R + JVM children
        )
    except Exception as exc:  # noqa: BLE001
        _append_log(log_path, f"Failed to launch: {exc}")
        _set_status(job_id, "error", finished=True)
        return

    with _procs_lock:
        _procs[job_id] = proc

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            _append_log(log_path, line)
        proc.wait()
    finally:
        with _procs_lock:
            _procs.pop(job_id, None)

    # A cancel sets status to "cancelled" before terminating; don't overwrite it.
    row = _job_row(job_id)
    if row and row["status"] == "cancelled":
        _append_log(log_path, "--- Cancelled ---")
        _db("UPDATE jobs SET finished_at = ? WHERE id = ?", (time.time(), job_id), commit=True)
    elif proc.returncode == 0:
        _append_log(log_path, "--- Finished successfully ---")
        _set_status(job_id, "done", finished=True)
    else:
        _append_log(log_path, f"--- Failed (exit code {proc.returncode}) ---")
        _set_status(job_id, "error", finished=True)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
app = FastAPI(title="OPAL OHDSI Runner", docs_url=None, redoc_url=None)


def _auth(x_runner_token: str = Header(default="")) -> None:
    # If no token is configured the runner refuses to start serving protected routes.
    if not RUNNER_TOKEN or x_runner_token != RUNNER_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid runner token")


class JobRequest(BaseModel):
    service: str
    cdm_name: str
    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str
    cdm_schema: str = Field(default="omop_cdm", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    results_schema: str = Field(default="omop_cdm", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    vocabulary_schema: str = Field(default="omop_cdm", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    cdm_version: str = Field(default="5.4", pattern=r"^[0-9]+\.[0-9]+$")
    cdm_source_name: str = ""
    small_cell_count: int = 5
    launched_by: str = ""


def _serialize(row: sqlite3.Row) -> dict:
    return {
        "job_id": row["id"],
        "service": row["service"],
        "cdm_name": row["cdm_name"],
        "status": row["status"],
        "launched_by": row["launched_by"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }


@app.get("/health")
def health() -> dict:
    return {"ok": True, "services": sorted(SERVICES)}


@app.post("/jobs", dependencies=[Depends(_auth)])
def create_job(req: JobRequest) -> dict:
    if req.service not in SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {req.service}")
    if not _CDM_NAME_RE.match(req.cdm_name):
        raise HTTPException(status_code=400, detail="Invalid cdm_name")

    _, out_sub = SERVICES[req.service]
    job_id = uuid.uuid4().hex
    out_dir = OUTPUT_DIR / req.cdm_name / out_sub
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = str(LOGS_DIR / f"{job_id}.log")
    Path(log_path).touch()

    env = {
        "DB_SYSTEM": "postgresql",
        "DB_HOST": req.db_host,
        "DB_PORT": str(req.db_port),
        "DB_NAME": req.db_name,
        "DB_USER": req.db_user,
        "DB_PASSWORD": req.db_password,
        "CDM_SCHEMA": req.cdm_schema,
        "RESULTS_SCHEMA": req.results_schema,
        "VOCABULARY_SCHEMA": req.vocabulary_schema,
        "CDM_VERSION": req.cdm_version,
        "CDM_SOURCE_NAME": req.cdm_source_name or req.cdm_name,
        "SMALL_CELL_COUNT": str(req.small_cell_count),
        "PATH_TO_DRIVER": PATH_TO_DRIVER,
        "OUTPUT_DIR": str(out_dir),
    }
    # CDM Onboarding consumes the DQD output of the same CDM.
    if req.service == "cdmonboarding":
        env["DQD_INPUT_DIR"] = str(OUTPUT_DIR / req.cdm_name / "dqd")

    _db(
        "INSERT INTO jobs (id, service, cdm_name, status, launched_by, created_at, output_dir, log_path) "
        "VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)",
        (job_id, req.service, req.cdm_name, req.launched_by, time.time(), str(out_dir), log_path),
        commit=True,
    )
    _append_log(log_path, f"Launching {req.service} for {req.cdm_name}...")
    _executor.submit(_run_job, job_id, req.service, env, log_path)
    return {"job_id": job_id}


@app.get("/jobs", dependencies=[Depends(_auth)])
def list_jobs(service: str | None = None) -> list[dict]:
    if service:
        cur = _db("SELECT * FROM jobs WHERE service = ? ORDER BY created_at DESC", (service,))
    else:
        cur = _db("SELECT * FROM jobs ORDER BY created_at DESC")
    return [_serialize(r) for r in cur.fetchall()]


@app.get("/jobs/{job_id}", dependencies=[Depends(_auth)])
def get_job(job_id: str) -> dict:
    row = _job_row(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return _serialize(row)


@app.get("/jobs/{job_id}/logs", dependencies=[Depends(_auth)])
def get_logs(job_id: str, offset: int = Query(0, ge=0)) -> dict:
    row = _job_row(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    lines: list[str] = []
    log_path = row["log_path"]
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    new_lines = lines[offset:]
    return {"status": row["status"], "lines": new_lines, "offset": len(lines)}


@app.post("/jobs/{job_id}/cancel", dependencies=[Depends(_auth)])
def cancel_job(job_id: str) -> dict:
    row = _job_row(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if row["status"] not in ("running", "queued"):
        raise HTTPException(status_code=400, detail="Job is not running")
    _set_status(job_id, "cancelled")
    with _procs_lock:
        proc = _procs.get(job_id)
    if proc and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    return {"ok": True}


def _safe_target(path: str) -> Path:
    base = OUTPUT_DIR.resolve()
    target = (OUTPUT_DIR / path).resolve() if path else base
    if target != base and base not in target.parents:
        raise HTTPException(status_code=403, detail="Access denied")
    return target


@app.get("/files/{path:path}", dependencies=[Depends(_auth)])
@app.get("/files/", dependencies=[Depends(_auth)])
def list_or_download(path: str = "") -> object:
    base = OUTPUT_DIR.resolve()
    target = _safe_target(path)
    if not target.exists():
        return []
    if target.is_file():
        return FileResponse(str(target), filename=target.name)
    items = []
    for entry in sorted(target.iterdir()):
        items.append({
            "name": entry.name,
            "path": str(entry.relative_to(base)),
            "is_dir": entry.is_dir(),
            "size": entry.stat().st_size if entry.is_file() else None,
        })
    return items
