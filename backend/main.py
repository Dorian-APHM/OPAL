"""
OPAL — OMOP Platform for Analytics & Lineage.
FastAPI application entry point.
"""
import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Query, Request, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

import psycopg2
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from config import CORS_ORIGINS, AUTH_ENABLED
from utils.crypto import DecryptionError
from utils.rate_limit import limiter
from audit.logger import AUDIT_LOG_DIR
from db.app_db import engine, get_db
from db.models import Base
from db.omop_connector import close_all_pools, evict_idle_pools

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="OPAL API",
    description="OMOP Platform for Analytics & Lineage",
    version="1.0.0",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------------------------------------------------------------------------
# OMOP connection pool lifecycle
# ---------------------------------------------------------------------------
import threading as _threading


def _pool_evictor():
    """Background thread that evicts idle OMOP connection pools every 60s."""
    while not _evictor_stop.is_set():
        _evictor_stop.wait(60)
        if not _evictor_stop.is_set():
            evict_idle_pools()


_evictor_stop = _threading.Event()
_evictor_thread: _threading.Thread | None = None


@app.on_event("startup")
def _start_pool_evictor():
    global _evictor_thread
    _evictor_thread = _threading.Thread(target=_pool_evictor, daemon=True, name="pool-evictor")
    _evictor_thread.start()
    logger.info("OMOP pool evictor started")


# ---------------------------------------------------------------------------
# WebSocket manager — capture the main event loop at startup
# ---------------------------------------------------------------------------
import asyncio as _asyncio
from utils.ws_manager import manager as _ws_manager, set_main_loop as _set_main_loop


@app.on_event("startup")
def _capture_event_loop():
    try:
        loop = _asyncio.get_running_loop()
        _set_main_loop(loop)
        logger.info("WebSocket manager bound to main event loop")
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Notification cleanup — purge old read notifications every 6 hours
# ---------------------------------------------------------------------------
def _notification_cleaner():
    """Background thread that deletes read notifications older than 30 days."""
    from datetime import datetime, timezone, timedelta
    from sqlalchemy.orm import Session as _Session
    from db.app_db import SessionLocal
    from db.models import Notification as _Notif

    while not _evictor_stop.is_set():
        _evictor_stop.wait(21600)  # 6 hours
        if _evictor_stop.is_set():
            break
        try:
            db: _Session = SessionLocal()
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            deleted = db.query(_Notif).filter(
                _Notif.read == 1,
                _Notif.created_at < cutoff,
            ).delete(synchronize_session=False)
            db.commit()
            db.close()
            if deleted:
                logger.info("Notification cleanup: deleted %d old read notifications", deleted)
        except Exception as e:
            logger.error("Notification cleanup error: %s", e)


_cleaner_thread: _threading.Thread | None = None


@app.on_event("startup")
def _start_notification_cleaner():
    global _cleaner_thread
    _cleaner_thread = _threading.Thread(target=_notification_cleaner, daemon=True, name="notif-cleaner")
    _cleaner_thread.start()
    logger.info("Notification cleaner started (purges read notifications >30d)")


# ---------------------------------------------------------------------------
# In-memory dict cleanup — evict stale/completed entries every 5 min
# ---------------------------------------------------------------------------
_TASK_TTL_SECONDS = 1800  # 30 minutes — auto-evict completed/abandoned tasks


def _inmemory_cleanup():
    """Background thread that cleans up stale entries in all in-memory task dicts."""
    import time
    import os

    while not _evictor_stop.is_set():
        _evictor_stop.wait(300)  # every 5 min
        if _evictor_stop.is_set():
            break
        try:
            # 1. Mapping suggestions
            from modules.mapping.router import _active_suggestions, _suggestions_lock, _cleanup_stale_suggestions
            with _suggestions_lock:
                _cleanup_stale_suggestions()

            # 2. Data extraction tasks — evict completed tasks older than TTL, clean up temp files
            from modules.datamanagement.router import _active_extractions, _extractions_lock
            now = time.time()
            with _extractions_lock:
                stale_ids = [
                    tid for tid, t in _active_extractions.items()
                    if t["status"] in ("completed", "error")
                    and t.get("completed_at") and now - t["completed_at"] > _TASK_TTL_SECONDS
                ]
                for tid in stale_ids:
                    task = _active_extractions.pop(tid)
                    csv_path = task.get("csv_path")
                    if csv_path:
                        try:
                            os.unlink(csv_path)
                        except OSError:
                            pass
                if stale_ids:
                    logger.info("Cleaned up %d stale extraction tasks", len(stale_ids))

            # 3. OHDSI tasks — evict finished tasks older than TTL
            from modules.ohdsi.router import _tasks, _lock as _ohdsi_lock
            with _ohdsi_lock:
                stale_ohdsi = [
                    tid for tid, t in _tasks.items()
                    if t.get("status") in ("completed", "error", "failed")
                    and t.get("finished_at") and now - t["finished_at"] > _TASK_TTL_SECONDS
                ]
                for tid in stale_ohdsi:
                    _tasks.pop(tid, None)
                if stale_ohdsi:
                    logger.info("Cleaned up %d stale OHDSI tasks", len(stale_ohdsi))

        except Exception as e:
            logger.error("In-memory cleanup error: %s", e)


_cleanup_thread: _threading.Thread | None = None


@app.on_event("startup")
def _start_inmemory_cleanup():
    global _cleanup_thread
    _cleanup_thread = _threading.Thread(target=_inmemory_cleanup, daemon=True, name="inmemory-cleanup")
    _cleanup_thread.start()
    logger.info("In-memory task cleanup started (evicts stale tasks every 5 min)")


# ---------------------------------------------------------------------------
# OHDSI output dirs — ensure per-CDM folders exist for all registered CDMs
# ---------------------------------------------------------------------------
@app.on_event("startup")
def _ensure_ohdsi_dirs():
    """Create OHDSI output sub-folders for every registered CDM at startup."""
    from db.app_db import SessionLocal
    from db.models import CdmConfig as _CdmConfig
    from modules.ohdsi.router import ensure_cdm_output_dirs
    try:
        db = SessionLocal()
        cdm_names = [c.name for c in db.query(_CdmConfig.name).all()]
        db.close()
        for name in cdm_names:
            ensure_cdm_output_dirs(name)
        if cdm_names:
            logger.info("OHDSI output dirs ensured for %d CDMs", len(cdm_names))
    except Exception:
        logger.warning("Could not create OHDSI output dirs at startup", exc_info=True)


@app.on_event("shutdown")
def _shutdown_pools():
    _evictor_stop.set()
    if _evictor_thread:
        _evictor_thread.join(timeout=5)
    close_all_pools()

# Global exception handlers
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    logger.warning("ValueError on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=400, content={"detail": "Invalid input"})


@app.exception_handler(psycopg2.OperationalError)
async def db_error_handler(request: Request, exc: psycopg2.OperationalError):
    logger.error("Database error: %s", exc)
    return JSONResponse(status_code=502, content={"detail": "External database connection error"})


@app.exception_handler(psycopg2.extensions.QueryCanceledError)
async def query_timeout_handler(request: Request, exc):
    logger.warning("Query timeout: %s", exc)
    return JSONResponse(status_code=504, content={"detail": "Query timed out. Try a simpler query or smaller dataset."})


@app.exception_handler(ConnectionError)
async def connection_error_handler(request: Request, exc: ConnectionError):
    logger.error("Connection pool exhausted: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable. Please try again shortly."})


@app.exception_handler(DecryptionError)
async def decryption_error_handler(request: Request, exc: DecryptionError):
    logger.error("Decryption failed: %s", exc)
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Accept-Language"],
)

# GZip compression for large responses
from starlette.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Audit logging (must be added before auth so it wraps the full request)
from audit.logger import AuditMiddleware
app.add_middleware(AuditMiddleware)

# Optional Keycloak auth
if AUTH_ENABLED:
    from auth.keycloak import KeycloakMiddleware
    app.add_middleware(KeycloakMiddleware)

# Create database tables
Base.metadata.create_all(bind=engine)

# Lightweight migrations for new columns on existing tables
from sqlalchemy import inspect as sa_inspect, text
_insp = sa_inspect(engine)
if _insp.has_table("cohort_versions"):
    _cols = {c["name"] for c in _insp.get_columns("cohort_versions")}
    with engine.begin() as _conn:
        if "characterization_json" not in _cols:
            _conn.execute(text("ALTER TABLE cohort_versions ADD COLUMN characterization_json JSON"))
        if "characterized_at" not in _cols:
            _conn.execute(text("ALTER TABLE cohort_versions ADD COLUMN characterized_at TIMESTAMP"))

if _insp.has_table("cohorts"):
    _cohort_cols = {c["name"] for c in _insp.get_columns("cohorts")}
    with engine.begin() as _conn:
        if "created_by" not in _cohort_cols:
            _conn.execute(text("ALTER TABLE cohorts ADD COLUMN created_by VARCHAR(255)"))
        if "shared_with_all" not in _cohort_cols:
            _conn.execute(text("ALTER TABLE cohorts ADD COLUMN shared_with_all INTEGER DEFAULT 0"))

# Import and register routers
from modules.cdm_router import router as cdm_router
from modules.quality.router import router as quality_router
from modules.cohort.router import router as cohort_router
from modules.mapping.router import router as mapping_router
from modules.concept.router import router as concept_router
from modules.ohdsi.router import router as ohdsi_router
from modules.concept_set.router import router as concept_set_router
from modules.incidence.router import router as incidence_router
from modules.estimation.router import router as estimation_router
from modules.datamanagement.router import router as datamanagement_router
from modules.cdm_access_router import router as cdm_access_router
from modules.notifications_router import router as notifications_router
from modules.favorites_router import router as favorites_router
from modules.saved_queries_router import router as saved_queries_router
from modules.cohort_templates_router import router as cohort_templates_router
from modules.search_router import router as search_router
from modules.cohort_sharing_router import router as cohort_sharing_router
from modules.groups_router import router as groups_router
from modules.admin_router import router as admin_router
from modules.lineage.router import router as lineage_router

app.include_router(cdm_router)
app.include_router(quality_router)
app.include_router(cohort_router)
app.include_router(mapping_router)
app.include_router(concept_router)
app.include_router(ohdsi_router)
app.include_router(concept_set_router)
app.include_router(incidence_router)
app.include_router(estimation_router)
app.include_router(datamanagement_router)
app.include_router(cdm_access_router)
app.include_router(notifications_router)
app.include_router(favorites_router)
app.include_router(saved_queries_router)
app.include_router(cohort_templates_router)
app.include_router(search_router)
app.include_router(cohort_sharing_router)
app.include_router(groups_router)
app.include_router(admin_router)
app.include_router(lineage_router)


# i18n endpoint
I18N_DIR = Path(__file__).parent / "i18n"


# P28 fix: cache translations at startup (only changes on deploy)
_i18n_cache: dict[str, dict] = {}
for _lang_file in I18N_DIR.glob("*.json"):
    with open(_lang_file, "r", encoding="utf-8") as _f:
        _i18n_cache[_lang_file.stem] = json.load(_f)


@app.get("/api/i18n/{lang}")
def get_translations(lang: str):
    """Return translation strings for a given language."""
    if lang not in _i18n_cache:
        return JSONResponse(status_code=404, content={"detail": f"Language '{lang}' not found"})
    return _i18n_cache[lang]


@app.get("/api/auth/me")
def auth_me(request: Request):
    """Return current user info and roles (from Keycloak token)."""
    user = getattr(request.state, "user", None)
    if not user or user.get("sub") == "anonymous":
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    return {
        "username": user.get("preferred_username", "unknown"),
        "email": user.get("email", ""),
        "roles": user.get("roles", []),
    }


@app.post("/api/auth/sse-ticket")
@limiter.limit("10/minute")
def create_sse_ticket_endpoint(request: Request):
    """Create a one-time-use ticket for SSE connections (replaces ?token= in URL)."""
    from auth.keycloak import create_sse_ticket
    user = getattr(request.state, "user", None)
    if not user or user.get("sub") in ("anonymous", "dev-user"):
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    ticket = create_sse_ticket(user)
    return {"ticket": ticket}


@app.get("/api/auth/permissions")
def auth_permissions(request: Request):
    """Return the resolved permissions for the current user based on their roles.
    Driven by permissions.yaml — the frontend uses this to show/hide pages and features.
    """
    from auth.permissions import build_frontend_permissions
    user = getattr(request.state, "user", None)
    if not user or user.get("sub") == "anonymous":
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    roles = user.get("roles", [])
    return build_frontend_permissions(roles)


# _require_admin is imported from admin_router for use by audit endpoints
from modules.admin_router import _require_admin


@app.get("/api/audit/logs")
def get_audit_logs(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    date: str | None = None,
    user: str | None = None,
    action: str | None = None,
    page: int = 1,
    page_size: int = Query(default=50, ge=1, le=500),
    admin_user=Depends(_require_admin),
):
    """Return audit log entries with filtering and pagination (admin only)."""
    from audit.logger import AUDIT_LOG_DIR
    import json as _json
    from datetime import date as _dt, timedelta

    # Determine date range
    if date:
        dates = [date]
    else:
        d_from = _dt.fromisoformat(date_from) if date_from else _dt.today()
        d_to = _dt.fromisoformat(date_to) if date_to else d_from
        dates = []
        d = d_to
        while d >= d_from:
            dates.append(d.isoformat())
            d -= timedelta(days=1)

    import heapq as _heapq

    # Two-pass approach: first count total matching entries, then collect only the page
    # This avoids loading all entries into memory at once.
    total = 0
    for dt_str in dates:
        log_file = AUDIT_LOG_DIR / f"{dt_str}.jsonl"
        if not log_file.exists():
            continue
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = _json.loads(line)
                    if user and entry.get("user") != user:
                        continue
                    if action and not entry.get("action", "").startswith(action):
                        continue
                    total += 1
                except _json.JSONDecodeError:
                    continue

    # Second pass: collect only the entries needed for the requested page
    # Use a heap to get top-N entries sorted by timestamp (descending)
    start = (page - 1) * page_size
    need = start + page_size  # We need the top `need` entries by timestamp
    # Use a min-heap of size `need` — keep the `need` most recent entries
    # Tuple: (timestamp, counter, entry) — counter avoids comparing dicts
    heap: list[tuple[str, int, dict]] = []
    counter = 0
    for dt_str in dates:
        log_file = AUDIT_LOG_DIR / f"{dt_str}.jsonl"
        if not log_file.exists():
            continue
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = _json.loads(line)
                    if user and entry.get("user") != user:
                        continue
                    if action and not entry.get("action", "").startswith(action):
                        continue
                    ts = entry.get("ts", "")
                    counter += 1
                    if len(heap) < need:
                        _heapq.heappush(heap, (ts, counter, entry))
                    elif ts > heap[0][0]:
                        _heapq.heapreplace(heap, (ts, counter, entry))
                except _json.JSONDecodeError:
                    continue

    # Sort the heap entries descending and slice for the page
    sorted_entries = [e for _, _, e in sorted(heap, key=lambda x: x[0], reverse=True)]
    return {
        "entries": sorted_entries[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@app.get("/api/audit/stats")
def get_audit_stats(request: Request, date_from: str | None = None, date_to: str | None = None, admin_user=Depends(_require_admin)):
    """Return audit log summary stats for a date range."""
    from audit.logger import AUDIT_LOG_DIR
    import json as _json
    from datetime import date as _dt, timedelta
    from collections import Counter

    d_from = _dt.fromisoformat(date_from) if date_from else _dt.today()
    d_to = _dt.fromisoformat(date_to) if date_to else d_from

    user_counts: Counter = Counter()
    action_counts: Counter = Counter()
    total = 0

    d = d_from
    while d <= d_to:
        log_file = AUDIT_LOG_DIR / f"{d.isoformat()}.jsonl"
        if log_file.exists():
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = _json.loads(line)
                        user_counts[entry.get("user", "unknown")] += 1
                        action_counts[entry.get("action", "unknown")] += 1
                        total += 1
                    except _json.JSONDecodeError:
                        continue
        d += timedelta(days=1)

    return {
        "total_events": total,
        "by_user": [{"user": u, "count": c} for u, c in user_counts.most_common(50)],
        "by_action": [{"action": a, "count": c} for a, c in action_counts.most_common(50)],
    }


@app.get("/api/audit/dates")
def get_audit_dates(request: Request, admin_user=Depends(_require_admin)):
    """Return list of dates that have audit log files."""
    from audit.logger import AUDIT_LOG_DIR
    dates = sorted(
        [f.stem for f in AUDIT_LOG_DIR.glob("*.jsonl")],
        reverse=True,
    )
    return {"dates": dates}


@app.get("/api/audit/export")
def export_audit_csv(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    user: str | None = None,
    action: str | None = None,
    admin_user=Depends(_require_admin),
):
    """Export audit logs as CSV."""
    import csv
    import io
    import json as _json
    from datetime import date as _dt, timedelta
    from audit.logger import AUDIT_LOG_DIR

    d_from = _dt.fromisoformat(date_from) if date_from else _dt.today()
    d_to = _dt.fromisoformat(date_to) if date_to else d_from

    from utils.csv_safety import csv_safe

    def _generate_csv():
        """Stream CSV line by line to avoid loading all entries in memory."""
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["timestamp", "user", "roles", "action", "method", "path", "status", "duration_ms", "ip"])
        yield buf.getvalue()

        d = d_from
        while d <= d_to:
            log_file = AUDIT_LOG_DIR / f"{d.isoformat()}.jsonl"
            if log_file.exists():
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = _json.loads(line)
                            if user and entry.get("user") != user:
                                continue
                            if action and not entry.get("action", "").startswith(action):
                                continue
                            row_buf = io.StringIO()
                            row_writer = csv.writer(row_buf)
                            row_writer.writerow([
                                csv_safe(entry.get("ts", "")),
                                csv_safe(entry.get("user", "")),
                                csv_safe(",".join(entry.get("roles", []))),
                                csv_safe(entry.get("action", "")),
                                csv_safe(entry.get("method", "")),
                                csv_safe(entry.get("path", "")),
                                entry.get("status", ""),
                                entry.get("duration_ms", ""),
                                csv_safe(entry.get("ip", "")),
                            ])
                            yield row_buf.getvalue()
                        except _json.JSONDecodeError:
                            continue
            d += timedelta(days=1)

    return StreamingResponse(
        _generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
    )


# ---------------------------------------------------------------------------
# WebSocket endpoint for real-time notifications
# ---------------------------------------------------------------------------
@app.websocket("/api/ws/notifications")
async def websocket_notifications(websocket: WebSocket, ticket: str = ""):
    """WebSocket endpoint for real-time notification push.

    Authentication uses a one-time SSE ticket (same mechanism as SSE streams)
    passed as ?ticket= query parameter.
    """
    from auth.keycloak import _redeem_sse_ticket

    user_info = _redeem_sse_ticket(ticket) if ticket else None
    if not user_info:
        await websocket.close(code=4001, reason="Invalid or expired ticket")
        return

    username = user_info.get("preferred_username", "anonymous")
    roles = user_info.get("roles", [])

    await _ws_manager.connect(websocket, username, roles)
    try:
        while True:
            # Keep connection alive; client sends pings, we just read and discard
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _ws_manager.disconnect(websocket, username)


@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "opal-backend"}


@app.get("/")
def root():
    return {"message": "OPAL API — OMOP Platform for Analytics & Lineage", "docs": "/docs"}
