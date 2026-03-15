"""
OPAL — OMOP Platform for Analytics & Lineage.
FastAPI application entry point.
"""
import json
import logging
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Query, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

import psycopg2
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from pydantic import BaseModel, Field

from config import CORS_ORIGINS, AUTH_ENABLED, KEYCLOAK_URL, KEYCLOAK_REALM
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
    """Background thread that evicts idle OMOP connection pools every 5 min."""
    while not _evictor_stop.is_set():
        _evictor_stop.wait(300)
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


@app.on_event("shutdown")
def _shutdown_pools():
    _evictor_stop.set()
    if _evictor_thread:
        _evictor_thread.join(timeout=5)
    close_all_pools()

# Global exception handlers
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


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


class AssignRoleRequest(BaseModel):
    role: str = Field(..., min_length=1, max_length=100)


class ToggleUserRequest(BaseModel):
    enabled: bool


def _require_admin(request: Request):
    """Raise 403 if the current user doesn't have the admin role."""
    user = getattr(request.state, "user", {})
    roles = user.get("roles", [])
    if "admin" not in roles:
        raise HTTPException(status_code=403, detail="Forbidden: admin role required")
    return user


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

    entries = []
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
                    entries.append(entry)
                except _json.JSONDecodeError:
                    continue

    entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
    start = (page - 1) * page_size
    return {
        "entries": entries[start:start + page_size],
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

    entries = []
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
                        entries.append(entry)
                    except _json.JSONDecodeError:
                        continue
        d += timedelta(days=1)

    output = io.StringIO()
    writer = csv.writer(output)
    from utils.csv_safety import csv_safe
    writer.writerow(["timestamp", "user", "roles", "action", "method", "path", "status", "duration_ms", "ip"])
    for e in entries:
        writer.writerow([
            csv_safe(e.get("ts", "")), csv_safe(e.get("user", "")), csv_safe(",".join(e.get("roles", []))),
            csv_safe(e.get("action", "")), csv_safe(e.get("method", "")), csv_safe(e.get("path", "")),
            e.get("status", ""), e.get("duration_ms", ""), csv_safe(e.get("ip", "")),
        ])
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
    )


# ──── Admin: User Management (Keycloak proxy) ────

@app.get("/api/admin/users")
def list_users(request: Request, admin_user=Depends(_require_admin)):
    """List Keycloak users with their roles (admin only)."""
    import requests as http_requests
    token = _get_keycloak_admin_token()
    if not token:
        return {"users": [], "error": "Keycloak admin unavailable"}

    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {token}"}

    # Collect users by OPAL role (avoids listing all LDAP users)
    opal_roles = ["admin", "data-manager", "chercheur", "medecin"]
    user_map = {}

    try:
        for role_name in opal_roles:
            resp = http_requests.get(
                f"{base}/roles/{role_name}/users?max=200", headers=headers, timeout=10
            )
            if not resp.ok:
                continue
            for u in resp.json():
                uid = u["id"]
                if uid not in user_map:
                    user_map[uid] = {
                        "id": uid,
                        "username": u.get("username", ""),
                        "email": u.get("email", ""),
                        "first_name": u.get("firstName", ""),
                        "last_name": u.get("lastName", ""),
                        "enabled": u.get("enabled", False),
                        "created_at": u.get("createdTimestamp"),
                        "roles": [],
                    }
                user_map[uid]["roles"].append(role_name)
    except Exception as e:
        logger.warning("Failed to fetch Keycloak users: %s", e)
        return {"users": [], "error": str(e)}

    return {"users": list(user_map.values())}


@app.post("/api/admin/users/{user_id}/roles")
def assign_role(user_id: str, request: Request, body: AssignRoleRequest, admin_user=Depends(_require_admin)):
    """Assign a role to a Keycloak user (admin only)."""
    import requests as http_requests
    role_name = body.role

    token = _get_keycloak_admin_token()
    if not token:
        return JSONResponse(status_code=503, content={"detail": "Keycloak admin unavailable"})

    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Get role representation
    try:
        role_resp = http_requests.get(f"{base}/roles/{role_name}", headers=headers, timeout=5)
        role_resp.raise_for_status()
        role_obj = role_resp.json()
    except Exception:
        return JSONResponse(status_code=404, content={"detail": f"Role '{role_name}' not found"})

    # Assign role
    try:
        resp = http_requests.post(
            f"{base}/users/{user_id}/role-mappings/realm",
            headers=headers, json=[role_obj], timeout=5,
        )
        resp.raise_for_status()
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Failed to assign role: {e}"})

    return {"status": "ok", "user_id": user_id, "role": role_name, "action": "assigned"}


@app.delete("/api/admin/users/{user_id}/roles/{role_name}")
def remove_role(user_id: str, role_name: str, request: Request, admin_user=Depends(_require_admin)):
    """Remove a role from a Keycloak user (admin only)."""
    import requests as http_requests
    token = _get_keycloak_admin_token()
    if not token:
        return JSONResponse(status_code=503, content={"detail": "Keycloak admin unavailable"})

    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        role_resp = http_requests.get(f"{base}/roles/{role_name}", headers=headers, timeout=5)
        role_resp.raise_for_status()
        role_obj = role_resp.json()
    except Exception:
        return JSONResponse(status_code=404, content={"detail": f"Role '{role_name}' not found"})

    try:
        resp = http_requests.delete(
            f"{base}/users/{user_id}/role-mappings/realm",
            headers=headers, json=[role_obj], timeout=5,
        )
        resp.raise_for_status()
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Failed to remove role: {e}"})

    return {"status": "ok", "user_id": user_id, "role": role_name, "action": "removed"}


@app.put("/api/admin/users/{user_id}/toggle")
def toggle_user(user_id: str, request: Request, body: ToggleUserRequest, admin_user=Depends(_require_admin)):
    """Enable or disable a Keycloak user (admin only)."""
    import requests as http_requests
    enabled = body.enabled
    token = _get_keycloak_admin_token()
    if not token:
        return JSONResponse(status_code=503, content={"detail": "Keycloak admin unavailable"})

    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        resp = http_requests.put(
            f"{base}/users/{user_id}", headers=headers, json={"enabled": enabled}, timeout=5,
        )
        resp.raise_for_status()
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Failed to update user: {e}"})

    return {"status": "ok", "user_id": user_id, "enabled": enabled}


def _get_keycloak_admin_token() -> str | None:
    """Get a Keycloak admin token using client credentials or admin password."""
    import requests as http_requests
    import os

    admin_user = os.getenv("KEYCLOAK_ADMIN", "")
    admin_pass = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "")

    if not admin_user or not admin_pass:
        logger.error("KEYCLOAK_ADMIN / KEYCLOAK_ADMIN_PASSWORD not configured")
        return None

    if admin_user == "admin" and admin_pass == "admin":
        logger.warning(
            "SECURITY: Keycloak admin credentials are set to default 'admin/admin'. "
            "Change KEYCLOAK_ADMIN and KEYCLOAK_ADMIN_PASSWORD in your .env file for production."
        )

    try:
        resp = http_requests.post(
            f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": admin_user,
                "password": admin_pass,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("access_token")
    except Exception as e:
        logger.warning("Failed to get Keycloak admin token: %s", e)
        return None


# ──── Access Requests (self-service sign-up) ────

@app.post("/api/access-requests")
@limiter.limit("5/minute")
def submit_access_request(request: Request, body: dict, db=Depends(get_db)):
    """Submit a new access request (public, no auth required)."""
    from db.models import AccessRequest

    required = ["username", "requested_role"]
    for field in required:
        if not body.get(field, "").strip():
            return JSONResponse(status_code=400, content={"detail": f"{field} is required"})

    role = body["requested_role"]
    if role not in ("admin", "data-manager", "chercheur", "medecin"):
        return JSONResponse(status_code=400, content={"detail": f"Invalid role: {role}"})

    existing = db.query(AccessRequest).filter(
        AccessRequest.username == body["username"],
        AccessRequest.status == "pending",
    ).first()
    if existing:
        return JSONResponse(status_code=409, content={"detail": "Une demande est deja en cours pour ce matricule"})

    req = AccessRequest(
        username=body["username"].strip(),
        email=body.get("email", "").strip(),
        first_name=body.get("first_name", "").strip(),
        last_name=body.get("last_name", "").strip(),
        requested_role=role,
    )
    db.add(req)
    db.flush()

    # Notify all admins about the new access request (role-targeted)
    from utils.notifications import notify
    notify(
        db, body["username"], "access_request",
        title=f"Nouvelle demande d'accès : {body['username']}",
        message=f"{body['username']} demande le rôle « {role} ».",
        link="/users",
        target_role="admin",
        item_id=str(req.id),
    )

    db.commit()
    return {"status": "ok", "id": req.id}


@app.get("/api/admin/access-requests")
def list_access_requests(request: Request, status_filter: str = "pending", admin_user=Depends(_require_admin), db=Depends(get_db)):
    """List access requests (admin only)."""
    from db.models import AccessRequest

    q = db.query(AccessRequest)
    if status_filter != "all":
        q = q.filter(AccessRequest.status == status_filter)
    requests_list = q.order_by(AccessRequest.created_at.desc()).all()
    return {
        "requests": [
            {
                "id": r.id,
                "username": r.username,
                "email": r.email,
                "first_name": r.first_name,
                "last_name": r.last_name,
                "requested_role": r.requested_role,
                "status": r.status,
                "reviewed_by": r.reviewed_by,
                "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in requests_list
        ]
    }


@app.post("/api/admin/access-requests/{request_id}/approve")
def approve_access_request(request_id: int, request: Request, admin_user=Depends(_require_admin), db=Depends(get_db)):
    """Approve an access request: create Keycloak user with temporary password (admin only)."""
    import requests as http_requests
    from datetime import datetime, timezone
    from db.models import AccessRequest

    ar = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not ar:
        return JSONResponse(status_code=404, content={"detail": "Request not found"})
    if ar.status != "pending":
        return JSONResponse(status_code=400, content={"detail": f"Request already {ar.status}"})

    # Create Keycloak user
    token = _get_keycloak_admin_token()
    if not token:
        return JSONResponse(status_code=503, content={"detail": "Keycloak admin unavailable"})

    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Find or create Keycloak user
    use_ldap = os.environ.get("KEYCLOAK_LDAP_ENABLED", "false").lower() == "true"
    kc_user_id = None

    # First, check if user already exists (LDAP or local)
    try:
        search_resp = http_requests.get(
            f"{base}/users?username={ar.username}&exact=true", headers=headers, timeout=10
        )
        existing = [u for u in search_resp.json() if u.get("username", "").lower() == ar.username.lower()] if search_resp.ok else []
        if existing:
            kc_user_id = existing[0]["id"]
    except Exception:
        pass

    # If user doesn't exist, create locally
    if not kc_user_id:
        user_payload = {
            "username": ar.username,
            "email": ar.email,
            "firstName": ar.first_name,
            "lastName": ar.last_name,
            "enabled": True,
        }
        temp_password = secrets.token_urlsafe(16)
        if not use_ldap:
            user_payload["credentials"] = [{
                "type": "password",
                "value": temp_password,
                "temporary": True,
            }]
        try:
            resp = http_requests.post(f"{base}/users", headers=headers, json=user_payload, timeout=10)
            resp.raise_for_status()
            location = resp.headers.get("Location", "")
            kc_user_id = location.rsplit("/", 1)[-1] if location else None
        except Exception as e:
            return JSONResponse(status_code=500, content={"detail": f"Failed to create Keycloak user: {e}"})

    # Assign the requested role
    if kc_user_id and ar.requested_role:
        try:
            role_resp = http_requests.get(
                f"{base}/roles/{ar.requested_role}", headers=headers, timeout=5
            )
            if role_resp.ok:
                role_obj = role_resp.json()
                http_requests.post(
                    f"{base}/users/{kc_user_id}/role-mappings/realm",
                    headers=headers, json=[role_obj], timeout=5,
                )
        except Exception:
            logger.warning("Failed to assign role %s to new user %s", ar.requested_role, ar.username)

    # Update request status
    user_info = getattr(request.state, "user", {})
    ar.status = "approved"
    ar.reviewed_by = user_info.get("preferred_username", "admin")
    ar.reviewed_at = datetime.now(timezone.utc)

    # Notify the requester
    from utils.notifications import notify
    notify(
        db, ar.username, "access_request",
        title="Demande d'accès approuvée",
        message=f"Votre demande d'accès avec le rôle « {ar.requested_role} » a été approuvée.",
        item_id=str(ar.id),
    )

    db.commit()

    result = {
        "status": "ok",
        "username": ar.username,
        "keycloak_user_id": kc_user_id,
    }
    if not use_ldap:
        result["temporary_password"] = temp_password
    else:
        result["auth_method"] = "ldap"
    return result


@app.post("/api/admin/users/add")
async def add_user_direct(request: Request, admin_user=Depends(_require_admin)):
    """Admin adds a user directly by matricule + role (admin only)."""
    import requests as http_requests

    body = await request.json()
    username = body.get("username", "").strip()
    role = body.get("role", "").strip()

    if not username:
        return JSONResponse(status_code=400, content={"detail": "Matricule requis"})
    if role not in ("admin", "data-manager", "chercheur", "medecin"):
        return JSONResponse(status_code=400, content={"detail": f"Role invalide: {role}"})

    token = _get_keycloak_admin_token()
    if not token:
        return JSONResponse(status_code=503, content={"detail": "Keycloak admin unavailable"})

    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    use_ldap = os.environ.get("KEYCLOAK_LDAP_ENABLED", "false").lower() == "true"
    kc_user_id = None

    # Find existing user (LDAP or local)
    try:
        search_resp = http_requests.get(
            f"{base}/users?username={username}&exact=true", headers=headers, timeout=10
        )
        existing = [u for u in search_resp.json() if u.get("username", "").lower() == username.lower()] if search_resp.ok else []
        if existing:
            kc_user_id = existing[0]["id"]
    except Exception:
        pass

    # Create if not found
    temp_password = None
    if not kc_user_id:
        temp_password = secrets.token_urlsafe(16)
        user_payload = {"username": username, "enabled": True}
        if not use_ldap:
            user_payload["credentials"] = [{"type": "password", "value": temp_password, "temporary": True}]
        try:
            resp = http_requests.post(f"{base}/users", headers=headers, json=user_payload, timeout=10)
            resp.raise_for_status()
            location = resp.headers.get("Location", "")
            kc_user_id = location.rsplit("/", 1)[-1] if location else None
        except Exception as e:
            return JSONResponse(status_code=500, content={"detail": f"Impossible de creer l'utilisateur: {e}"})

    if not kc_user_id:
        return JSONResponse(status_code=500, content={"detail": "Impossible de trouver ou creer l'utilisateur"})

    # Assign role
    try:
        role_resp = http_requests.get(f"{base}/roles/{role}", headers=headers, timeout=5)
        if role_resp.ok:
            role_obj = role_resp.json()
            assign_resp = http_requests.post(
                f"{base}/users/{kc_user_id}/role-mappings/realm",
                headers=headers, json=[role_obj], timeout=5,
            )
            assign_resp.raise_for_status()
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Utilisateur cree mais echec assignation role: {e}"})

    result = {"status": "ok", "username": username, "role": role, "keycloak_user_id": kc_user_id}
    if temp_password and not use_ldap:
        result["temporary_password"] = temp_password
    return result


@app.post("/api/admin/access-requests/{request_id}/reject")
def reject_access_request(request_id: int, request: Request, admin_user=Depends(_require_admin), db=Depends(get_db)):
    """Reject an access request (admin only)."""
    from datetime import datetime, timezone
    from db.models import AccessRequest

    ar = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not ar:
        return JSONResponse(status_code=404, content={"detail": "Request not found"})
    if ar.status != "pending":
        return JSONResponse(status_code=400, content={"detail": f"Request already {ar.status}"})

    user_info = getattr(request.state, "user", {})
    ar.status = "rejected"
    ar.reviewed_by = user_info.get("preferred_username", "admin")
    ar.reviewed_at = datetime.now(timezone.utc)

    from utils.notifications import notify
    notify(
        db, ar.username, "access_request",
        title="Demande d'accès refusée",
        message=f"Votre demande d'accès avec le rôle « {ar.requested_role} » a été refusée.",
        item_id=str(ar.id),
    )

    db.commit()

    return {"status": "ok", "id": ar.id}


@app.get("/api/users/list")
def list_opal_users(request: Request):
    """List usernames of all users who have an OPAL role.

    Available to any authenticated user (for sharing dropdowns).
    Returns only usernames — no admin details.
    """
    import requests as http_requests
    token = _get_keycloak_admin_token()
    if not token:
        return {"users": []}

    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {token}"}
    opal_roles = ["admin", "data-manager", "chercheur", "medecin"]
    usernames = set()

    try:
        for role_name in opal_roles:
            resp = http_requests.get(
                f"{base}/roles/{role_name}/users?max=500", headers=headers, timeout=10
            )
            if not resp.ok:
                continue
            for u in resp.json():
                uname = u.get("username", "")
                if uname:
                    usernames.add(uname)
    except Exception as e:
        logger.warning("Failed to fetch OPAL users: %s", e)
        return {"users": []}

    return {"users": sorted(usernames)}


@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "opal-backend"}


@app.get("/")
def root():
    return {"message": "OPAL API — OMOP Platform for Analytics & Lineage", "docs": "/docs"}
