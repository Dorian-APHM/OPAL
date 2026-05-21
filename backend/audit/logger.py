"""
Per-user audit logging for OPAL.

Logs user actions as structured JSON lines into daily rotating files.
Directory structure:
    /app/logs/  (mounted to ./backend/logs on host)
        2026-03-05.jsonl
        2026-03-06.jsonl
        ...

Each line is a JSON object:
{
    "ts": "2026-03-05T14:23:01.123Z",
    "user": "jdoe",
    "roles": ["chercheur"],
    "action": "quality.analyze",
    "method": "POST",
    "path": "/api/quality/analyze",
    "status": 200,
    "duration_ms": 1234,
    "detail": {"cdm": "my_cdm", "domain": "Condition"},
    "ip": "192.0.2.1"
}
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from config import BASE_DIR

AUDIT_LOG_DIR = BASE_DIR / "logs"
AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)

# Retention: delete log files older than this many days (default 90)
AUDIT_LOG_RETENTION_DAYS = int(os.getenv("AUDIT_LOG_RETENTION_DAYS", "90"))

logger = logging.getLogger("opal.audit")


def cleanup_old_logs() -> int:
    """Remove audit log files older than AUDIT_LOG_RETENTION_DAYS. Returns count removed."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=AUDIT_LOG_RETENTION_DAYS)
    removed = 0
    for f in AUDIT_LOG_DIR.glob("*.jsonl"):
        try:
            file_date = datetime.strptime(f.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if file_date < cutoff:
                f.unlink()
                removed += 1
        except (ValueError, OSError):
            continue
    if removed:
        logger.info("Cleaned up %d audit log files older than %d days", removed, AUDIT_LOG_RETENTION_DAYS)
    return removed


# Run cleanup on module load (at startup)
try:
    cleanup_old_logs()
except Exception:
    logger.warning("Failed to clean up old audit logs", exc_info=True)

# Action labels derived from method + path prefix
ACTION_MAP = [
    ("POST", "/api/quality/analyze", "quality.analyze"),
    ("POST", "/api/quality/compare", "quality.compare"),
    ("POST", "/api/cohorts/count", "cohort.count"),
    ("POST", "/api/cohorts/attrition", "cohort.attrition"),
    ("POST", "/api/cohorts/sample", "cohort.sample"),
    ("POST", "/api/cohorts/export", "cohort.export"),
    ("POST", "/api/cohorts/", "cohort.create"),
    ("PUT", "/api/cohorts/", "cohort.update"),
    ("DELETE", "/api/cohorts/", "cohort.delete"),
    ("POST", "/api/cohorts/concepts/search", "cohort.concept_search"),
    ("POST", "/api/mapping/suggest", "mapping.suggest"),
    ("POST", "/api/mapping/decide", "mapping.decide"),
    ("POST", "/api/mapping/apply", "mapping.apply"),
    ("POST", "/api/mapping/history/", "mapping.rollback"),
    ("POST", "/api/mapping/sapbert/upload", "mapping.upload_sapbert"),
    ("DELETE", "/api/mapping/sapbert/", "mapping.delete_sapbert"),
    ("POST", "/api/mapping/reference/upload", "mapping.upload_reference"),
    ("DELETE", "/api/mapping/reference/", "mapping.delete_reference"),
    ("POST", "/api/mapping/decide/bulk", "mapping.decide_bulk"),
    ("POST", "/api/cdm/", "cdm.create"),
    ("PUT", "/api/cdm/", "cdm.update"),
    ("DELETE", "/api/cdm/", "cdm.delete"),
    ("POST", "/api/cdm/test", "cdm.test"),
    ("POST", "/api/ohdsi/run/", "ohdsi.run"),
    ("POST", "/api/ohdsi/stop/", "ohdsi.stop"),
    ("GET", "/api/concepts/", "concept.search"),
    ("GET", "/api/concepts/search-source-value", "concept.search_source"),
]

# Paths to skip (high-frequency, low-value)
SKIP_PATHS = {"/api/health", "/api/i18n", "/api/auth", "/api/access-requests", "/docs", "/openapi.json", "/", "/redoc", "/api/ohdsi/logs"}


def _resolve_action(method: str, path: str) -> str | None:
    """Map HTTP method + path to a human-readable action label."""
    for m, prefix, action in ACTION_MAP:
        if method == m and path.startswith(prefix):
            return action
    return None


def _get_log_file(dt: datetime) -> Path:
    return AUDIT_LOG_DIR / f"{dt.strftime('%Y-%m-%d')}.jsonl"


def write_audit_log(entry: dict[str, Any]) -> None:
    """Append a JSON line to today's audit log file."""
    try:
        now = entry.get("ts", datetime.now(timezone.utc))
        if isinstance(now, str):
            now = datetime.fromisoformat(now)
        log_file = _get_log_file(now)
        is_new = not log_file.exists()
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if is_new:
            os.chmod(log_file, 0o640)
    except Exception:
        logger.exception("Failed to write audit log entry")


class AuditMiddleware(BaseHTTPMiddleware):
    """Middleware that logs user actions to daily JSONL files."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        method = request.method

        # Skip non-actionable paths
        if path == "/" or any(path.startswith(p) for p in SKIP_PATHS if p != "/"):
            return await call_next(request)

        # Skip GET requests that aren't searches (list/read operations are low-value)
        action = _resolve_action(method, path)
        if action is None and method == "GET":
            return await call_next(request)

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000)

        # Extract user from request state (set by KeycloakMiddleware)
        user = getattr(request.state, "user", None) or {}
        username = user.get("preferred_username", "anonymous")
        roles = user.get("roles", [])

        if username == "anonymous":
            return response

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "user": username,
            "roles": roles,
            "action": action or f"{method} {path}",
            "method": method,
            "path": path,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "ip": request.client.host if request.client else "",
        }

        # Add query params for context (cdm_name, domain, etc.)
        # Mask sensitive values to avoid leaking credentials in audit logs
        _SENSITIVE_KEYS = {"password", "token", "ticket", "secret", "secret_key", "db_password"}
        params = dict(request.query_params)
        if params:
            entry["params"] = {
                k: "***" if k.lower() in _SENSITIVE_KEYS else v
                for k, v in params.items()
            }

        write_audit_log(entry)

        return response
