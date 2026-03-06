"""
OPAL — OMOP Platform for Analytics & Lineage.
FastAPI application entry point.
"""
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

import psycopg2

from config import CORS_ORIGINS, AUTH_ENABLED, KEYCLOAK_URL, KEYCLOAK_REALM
from audit.logger import AUDIT_LOG_DIR
from db.app_db import engine, get_db
from db.models import Base

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


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# Import and register routers
from modules.cdm_router import router as cdm_router
from modules.quality.router import router as quality_router
from modules.cohort.router import router as cohort_router
from modules.mapping.router import router as mapping_router
from modules.concept.router import router as concept_router
from modules.ohdsi.router import router as ohdsi_router

app.include_router(cdm_router)
app.include_router(quality_router)
app.include_router(cohort_router)
app.include_router(mapping_router)
app.include_router(concept_router)
app.include_router(ohdsi_router)


# i18n endpoint
I18N_DIR = Path(__file__).parent / "i18n"


@app.get("/api/i18n/{lang}")
def get_translations(lang: str):
    """Return translation strings for a given language."""
    filepath = I18N_DIR / f"{lang}.json"
    if not filepath.exists():
        return JSONResponse(status_code=404, content={"detail": f"Language '{lang}' not found"})
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


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


@app.get("/api/audit/logs")
def get_audit_logs(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    date: str | None = None,
    user: str | None = None,
    action: str | None = None,
    page: int = 1,
    page_size: int = 50,
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
    for dt_str in dates:
        log_file = AUDIT_LOG_DIR / f"{dt_str}.jsonl"
        if not log_file.exists():
            continue
        for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
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

    entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
    total = len(entries)
    start = (page - 1) * page_size
    return {
        "entries": entries[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@app.get("/api/audit/stats")
def get_audit_stats(request: Request, date_from: str | None = None, date_to: str | None = None):
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
            for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
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
def get_audit_dates(request: Request):
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
):
    """Export audit logs as CSV."""
    import csv
    import io
    import json as _json
    from datetime import date as _dt, timedelta

    d_from = _dt.fromisoformat(date_from) if date_from else _dt.today()
    d_to = _dt.fromisoformat(date_to) if date_to else d_from

    entries = []
    d = d_from
    while d <= d_to:
        log_file = AUDIT_LOG_DIR / f"{d.isoformat()}.jsonl"
        if log_file.exists():
            for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
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
    writer.writerow(["timestamp", "user", "roles", "action", "method", "path", "status", "duration_ms", "ip"])
    for e in entries:
        writer.writerow([
            e.get("ts", ""), e.get("user", ""), ",".join(e.get("roles", [])),
            e.get("action", ""), e.get("method", ""), e.get("path", ""),
            e.get("status", ""), e.get("duration_ms", ""), e.get("ip", ""),
        ])
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
    )


# ──── Admin: User Management (Keycloak proxy) ────

@app.get("/api/admin/users")
def list_users(request: Request):
    """List Keycloak users with their roles (admin only)."""
    import requests as http_requests
    token = _get_keycloak_admin_token()
    if not token:
        return {"users": [], "error": "Keycloak admin unavailable"}

    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = http_requests.get(f"{base}/users?max=200", headers=headers, timeout=10)
        resp.raise_for_status()
        users = resp.json()
    except Exception as e:
        logger.warning("Failed to fetch Keycloak users: %s", e)
        return {"users": [], "error": str(e)}

    # Fetch role mappings for each user
    result = []
    for u in users:
        user_id = u["id"]
        try:
            roles_resp = http_requests.get(
                f"{base}/users/{user_id}/role-mappings/realm", headers=headers, timeout=5
            )
            user_roles = [r["name"] for r in roles_resp.json()] if roles_resp.ok else []
        except Exception:
            user_roles = []

        result.append({
            "id": user_id,
            "username": u.get("username", ""),
            "email": u.get("email", ""),
            "first_name": u.get("firstName", ""),
            "last_name": u.get("lastName", ""),
            "enabled": u.get("enabled", False),
            "created_at": u.get("createdTimestamp"),
            "roles": user_roles,
        })

    return {"users": result}


@app.post("/api/admin/users/{user_id}/roles")
def assign_role(user_id: str, request: Request, body: dict):
    """Assign a role to a Keycloak user."""
    import requests as http_requests
    role_name = body.get("role")
    if not role_name:
        return JSONResponse(status_code=400, content={"detail": "role is required"})

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
def remove_role(user_id: str, role_name: str, request: Request):
    """Remove a role from a Keycloak user."""
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
def toggle_user(user_id: str, request: Request, body: dict):
    """Enable or disable a Keycloak user."""
    import requests as http_requests
    enabled = body.get("enabled", True)
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

    admin_user = os.getenv("KEYCLOAK_ADMIN", "admin")
    admin_pass = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin")

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
def submit_access_request(request: Request, body: dict, db=Depends(get_db)):
    """Submit a new access request (public, no auth required)."""
    from db.models import AccessRequest

    required = ["username", "email", "first_name", "last_name", "requested_role"]
    for field in required:
        if not body.get(field, "").strip():
            return JSONResponse(status_code=400, content={"detail": f"{field} is required"})

    role = body["requested_role"]
    if role not in ("admin", "omop-dim", "chercheur", "medecin"):
        return JSONResponse(status_code=400, content={"detail": f"Invalid role: {role}"})

    existing = db.query(AccessRequest).filter(
        AccessRequest.username == body["username"]
    ).first()
    if existing:
        return JSONResponse(status_code=409, content={"detail": "A request for this username already exists"})

    req = AccessRequest(
        username=body["username"].strip(),
        email=body["email"].strip(),
        first_name=body["first_name"].strip(),
        last_name=body["last_name"].strip(),
        requested_role=role,
    )
    db.add(req)
    db.commit()
    return {"status": "ok", "id": req.id}


@app.get("/api/admin/access-requests")
def list_access_requests(request: Request, status_filter: str = "pending", db=Depends(get_db)):
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
def approve_access_request(request_id: int, request: Request, db=Depends(get_db)):
    """Approve an access request: create Keycloak user with temporary password."""
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

    # Create user with temporary password = username
    user_payload = {
        "username": ar.username,
        "email": ar.email,
        "firstName": ar.first_name,
        "lastName": ar.last_name,
        "enabled": True,
        "credentials": [{
            "type": "password",
            "value": ar.username,
            "temporary": True,
        }],
    }
    try:
        resp = http_requests.post(f"{base}/users", headers=headers, json=user_payload, timeout=10)
        if resp.status_code == 409:
            return JSONResponse(status_code=409, content={"detail": "User already exists in Keycloak"})
        resp.raise_for_status()
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Failed to create Keycloak user: {e}"})

    # Get the created user ID from Location header
    location = resp.headers.get("Location", "")
    kc_user_id = location.rsplit("/", 1)[-1] if location else None

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
    db.commit()

    return {
        "status": "ok",
        "username": ar.username,
        "keycloak_user_id": kc_user_id,
        "temporary_password": ar.username,
    }


@app.post("/api/admin/access-requests/{request_id}/reject")
def reject_access_request(request_id: int, request: Request, db=Depends(get_db)):
    """Reject an access request."""
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
    db.commit()

    return {"status": "ok", "id": ar.id}


@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "opal-backend"}


@app.get("/")
def root():
    return {"message": "OPAL API — OMOP Platform for Analytics & Lineage", "docs": "/docs"}
