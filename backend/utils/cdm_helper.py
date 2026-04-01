"""
Centralized CDM connection helper.

Avoids duplicating the CDM lookup + decrypt + connect + schema logic
across 5+ routers.
"""
import logging

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from db.models import CdmConfig, AnalysisSettings
from db.omop_connector import get_omop_connection
from utils.crypto import decrypt_password
from utils.sql_safety import safe_identifier
from config import DEFAULT_OMOP_SCHEMA


def get_cdm_connection(db: Session, cdm_name: str):
    """
    Look up a CDM by name, decrypt credentials, open a pooled connection,
    and return (connection, validated_schema).

    Raises HTTPException 404 if CDM not found.
    """
    cdm = db.query(CdmConfig).filter(CdmConfig.name == cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{cdm_name}' not found")
    password = decrypt_password(cdm.db_password_encrypted)
    conn = get_omop_connection(cdm.db_host, cdm.db_port, cdm.db_name, cdm.db_user, password)
    settings = db.query(AnalysisSettings).filter(AnalysisSettings.cdm_name == cdm_name).first()
    raw_schema = settings.omop_schema if settings else cdm.omop_schema or DEFAULT_OMOP_SCHEMA
    schema = safe_identifier(raw_schema)
    return conn, schema


_logger = logging.getLogger(__name__)

# Cache for column existence checks: (cdm_name, schema, table, column) -> bool
_column_exists_cache: dict[tuple[str, str, str, str], bool] = {}


def _column_exists(conn, schema: str, table: str, column: str) -> bool:
    """Check if a column exists in a table via information_schema (cached)."""
    # Use the CDM connection's dsn as part of the cache key
    dsn = conn.dsn if hasattr(conn, 'dsn') else str(id(conn))
    cache_key = (dsn, schema, table, column)
    if cache_key in _column_exists_cache:
        return _column_exists_cache[cache_key]
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_name = %s LIMIT 1",
            (schema, table, column),
        )
        exists = cur.fetchone() is not None
        cur.close()
    except Exception:
        exists = False
    _column_exists_cache[cache_key] = exists
    return exists


def get_domain_config(conn, schema: str, domain: str) -> dict:
    """Return DOMAIN_CONFIG for a domain, stripping optional columns that don't exist in the CDM.

    This ensures columns like 'source_name' (drug_source_name, measurement_source_name)
    that are not part of the standard OMOP CDM spec are only included when actually present.
    """
    from config import DOMAIN_CONFIG
    cfg = DOMAIN_CONFIG.get(domain)
    if not cfg:
        return {}
    cfg = dict(cfg)  # shallow copy to avoid mutating the global

    # Check optional columns that may be absent from certain CDMs
    optional_cols = ["source_name", "source_concept_id", "source_atc"]
    table = cfg.get("table", "")
    for opt in optional_cols:
        col_name = cfg.get(opt)
        if col_name and not _column_exists(conn, schema, table, col_name):
            _logger.info(
                "Optional column %s.%s.%s not found — disabling '%s' for domain %s",
                schema, table, col_name, opt, domain,
            )
            del cfg[opt]

    return cfg


def check_cdm_access(request: Request, cdm_name: str) -> None:
    """
    Verify the current user has access to the given CDM.

    The Keycloak middleware automatically checks CDM access when cdm_name
    appears as a query parameter or in a recognised path segment. However,
    POST endpoints that receive cdm_name inside the JSON request body bypass
    the middleware check. Call this function in those endpoints to enforce
    access control.

    Does nothing when AUTH_ENABLED is false (dev mode).

    Raises HTTPException 403 if access is denied.
    """
    from config import AUTH_ENABLED

    if not AUTH_ENABLED:
        return

    user_info = getattr(request.state, "user", None)
    if not user_info:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Delegate to the same logic the middleware uses
    from auth.keycloak import _check_cdm_access

    if not _check_cdm_access(cdm_name, user_info):
        raise HTTPException(status_code=403, detail=f"Access denied to CDM '{cdm_name}'")
