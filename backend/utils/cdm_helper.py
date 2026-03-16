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
