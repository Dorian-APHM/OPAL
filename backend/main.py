"""
OPAL — OMOP Platform for Analytics & Lineage.
FastAPI application entry point.
"""
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import psycopg2

from config import CORS_ORIGINS, AUTH_ENABLED
from db.app_db import engine
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
def get_audit_logs(request: Request, date: str | None = None, user: str | None = None, limit: int = 200):
    """Return audit log entries (admin only, handled by role middleware)."""
    from audit.logger import AUDIT_LOG_DIR
    import json as _json
    from datetime import date as _date

    target_date = date or _date.today().isoformat()
    log_file = AUDIT_LOG_DIR / f"{target_date}.jsonl"
    if not log_file.exists():
        return {"date": target_date, "entries": []}

    entries = []
    for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
        if not line:
            continue
        try:
            entry = _json.loads(line)
            if user and entry.get("user") != user:
                continue
            entries.append(entry)
        except _json.JSONDecodeError:
            continue

    # Return most recent first, limited
    entries.reverse()
    return {"date": target_date, "entries": entries[:limit]}


@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "opal-backend"}


@app.get("/")
def root():
    return {"message": "OPAL API — OMOP Platform for Analytics & Lineage", "docs": "/docs"}
