"""
CDM management API endpoints — CRUD for CDM connections.
"""
import ipaddress
import logging
import re
import socket

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session

from db.app_db import get_db
from db.models import CdmConfig, AnalysisSettings
from db.omop_connector import test_omop_connection, invalidate_pool
from utils.crypto import encrypt_password, decrypt_password
from utils.notifications import notify
from config import DEFAULT_OMOP_SCHEMA

router = APIRouter(prefix="/api/cdm", tags=["cdm"])


def _validate_db_host(host: str) -> str:
    """Validate db_host to prevent SSRF attacks.

    Rejects loopback, link-local, metadata endpoints, and other dangerous targets.
    """
    host = host.strip()
    if not host:
        raise ValueError("db_host must not be empty")

    # Reject common dangerous hostnames
    dangerous_hostnames = {"localhost", "metadata.google.internal", "instance-data"}
    if host.lower() in dangerous_hostnames:
        raise ValueError(f"Hostname '{host}' is not allowed")

    # Try to parse as IP address directly
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_loopback or addr.is_link_local or addr.is_multicast:
            raise ValueError(f"IP address '{host}' is not allowed (loopback/link-local/multicast)")
        # Block cloud metadata IP (169.254.169.254)
        if str(addr) == "169.254.169.254":
            raise ValueError(f"IP address '{host}' is not allowed (cloud metadata endpoint)")
        return host
    except ValueError as e:
        if "is not allowed" in str(e):
            raise
        # Not an IP — treat as hostname, continue validation

    # Validate hostname format (RFC 1123)
    hostname_re = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$")
    if not hostname_re.match(host):
        raise ValueError(f"Invalid hostname format: '{host}'")

    # Resolve hostname and check resolved IP
    try:
        resolved = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in resolved:
            ip_str = sockaddr[0]
            addr = ipaddress.ip_address(ip_str)
            if addr.is_loopback or addr.is_link_local or addr.is_multicast:
                raise ValueError(f"Hostname '{host}' resolves to forbidden address {ip_str}")
            if str(addr) == "169.254.169.254":
                raise ValueError(f"Hostname '{host}' resolves to cloud metadata endpoint")
    except socket.gaierror:
        # Cannot resolve — allow it (may be reachable later from the backend container)
        pass

    return host


class CdmCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    db_host: str = Field(..., min_length=1, max_length=255)
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = Field(..., min_length=1, max_length=255)
    db_user: str = Field(..., min_length=1, max_length=255)
    db_password: str = Field(..., min_length=1, max_length=1000)
    omop_schema: str = Field(default=DEFAULT_OMOP_SCHEMA, max_length=255, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")

    @validator("db_host")
    def validate_host(cls, v):
        return _validate_db_host(v)


class CdmTestRequest(BaseModel):
    db_host: str = Field(..., min_length=1, max_length=255)
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = Field(..., min_length=1, max_length=255)
    db_user: str = Field(..., min_length=1, max_length=255)
    db_password: str = Field(..., min_length=1, max_length=1000)

    @validator("db_host")
    def validate_host(cls, v):
        return _validate_db_host(v)


class CdmUpdateRequest(BaseModel):
    db_host: str | None = Field(default=None, max_length=255)
    db_port: int | None = Field(default=None, ge=1, le=65535)
    db_name: str | None = Field(default=None, max_length=255)
    db_user: str | None = Field(default=None, max_length=255)
    db_password: str | None = Field(default=None, max_length=1000)
    omop_schema: str | None = Field(default=None, max_length=255, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")

    @validator("db_host")
    def validate_host(cls, v):
        if v is not None:
            return _validate_db_host(v)
        return v


class SettingsUpdateRequest(BaseModel):
    omop_schema: str | None = Field(default=None, max_length=255, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    top_unmapped_terms: int | None = Field(default=None, ge=1, le=1000)
    top_concepts: int | None = Field(default=None, ge=1, le=1000)
    max_records_per_person: int | None = Field(default=None, ge=1, le=10000)
    max_observation_months: int | None = Field(default=None, ge=1, le=1200)
    comparison_alert_threshold: float | None = Field(default=None, ge=0.0, le=100.0)


@router.get("/")
def list_cdms(db: Session = Depends(get_db)):
    """List all registered CDM connections."""
    cdms = db.query(CdmConfig).order_by(CdmConfig.name).all()
    return {
        "cdms": [
            {
                "id": c.id,
                "name": c.name,
                "db_host": c.db_host,
                "db_port": c.db_port,
                "db_name": c.db_name,
                "db_user": c.db_user,
                "omop_schema": c.omop_schema,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in cdms
        ]
    }


@router.post("/")
def create_cdm(req: CdmCreateRequest, request: Request, db: Session = Depends(get_db)):
    """Register a new CDM connection."""
    existing = db.query(CdmConfig).filter(CdmConfig.name == req.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"CDM '{req.name}' already exists")

    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "system")

    cdm = CdmConfig(
        name=req.name,
        db_host=req.db_host,
        db_port=req.db_port,
        db_name=req.db_name,
        db_user=req.db_user,
        db_password_encrypted=encrypt_password(req.db_password),
        omop_schema=req.omop_schema,
    )
    db.add(cdm)

    try:
        notify(
            db, username, "cdm_created",
            title=f"Nouveau CDM : {req.name}",
            message=f"{username} a enregistré la base CDM « {req.name} ».",
            link="/cdm",
            target_role="admin",
            item_id=req.name,
        )

        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to create CDM '%s'", req.name)
        raise HTTPException(status_code=500, detail="Failed to register CDM")
    db.refresh(cdm)

    return {
        "id": cdm.id,
        "name": cdm.name,
        "message": f"CDM '{cdm.name}' registered successfully",
    }


@router.post("/test")
def test_connection(req: CdmTestRequest):
    """Test a CDM database connection without saving it."""
    result = test_omop_connection(req.db_host, req.db_port, req.db_name, req.db_user, req.db_password)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result["message"])
    return result


@router.post("/{cdm_name}/test")
def test_saved_connection(cdm_name: str, db: Session = Depends(get_db)):
    """Test connectivity of a saved CDM."""
    cdm = db.query(CdmConfig).filter(CdmConfig.name == cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{cdm_name}' not found")

    password = decrypt_password(cdm.db_password_encrypted)
    result = test_omop_connection(cdm.db_host, cdm.db_port, cdm.db_name, cdm.db_user, password)
    return result


@router.put("/{cdm_name}")
def update_cdm(cdm_name: str, req: CdmUpdateRequest, request: Request, db: Session = Depends(get_db)):
    """Update a CDM connection."""
    cdm = db.query(CdmConfig).filter(CdmConfig.name == cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{cdm_name}' not found")

    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "system")

    # Snapshot old connection params before update (for pool invalidation)
    old_host, old_port, old_dbname, old_user = cdm.db_host, cdm.db_port, cdm.db_name, cdm.db_user

    if req.db_host is not None:
        cdm.db_host = req.db_host
    if req.db_port is not None:
        cdm.db_port = req.db_port
    if req.db_name is not None:
        cdm.db_name = req.db_name
    if req.db_user is not None:
        cdm.db_user = req.db_user
    if req.db_password is not None:
        cdm.db_password_encrypted = encrypt_password(req.db_password)
    if req.omop_schema is not None:
        cdm.omop_schema = req.omop_schema

    notify(
        db, username, "cdm_updated",
        title=f"CDM modifié : {cdm_name}",
        message=f"{username} a modifié la configuration de « {cdm_name} ».",
        link="/cdm",
        target_role="admin",
        item_id=cdm_name,
    )

    db.commit()

    # Invalidate the old pool so next request creates a fresh one
    invalidate_pool(old_host, old_port, old_dbname, old_user)

    return {"message": f"CDM '{cdm_name}' updated successfully"}


@router.delete("/{cdm_name}")
def delete_cdm(cdm_name: str, request: Request, db: Session = Depends(get_db)):
    """Delete a CDM connection and all associated data."""
    from db.models import (
        AnalysisSnapshot, AnalysisSettings, Cohort, CohortVersion, CohortShare,
        MappingDecision, CdmAccess, CdmGroupAccess, ConceptSet,
        IncidenceAnalysis, EstimationAnalysis, SavedQuery,
    )

    cdm = db.query(CdmConfig).filter(CdmConfig.name == cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{cdm_name}' not found")

    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "system")

    notify(
        db, username, "cdm_deleted",
        title=f"CDM supprimé : {cdm_name}",
        message=f"{username} a supprimé la base CDM « {cdm_name} » et toutes ses données associées.",
        link="/cdm",
        target_role="admin",
        item_id=cdm_name,
    )

    # Invalidate pool before deleting config
    invalidate_pool(cdm.db_host, cdm.db_port, cdm.db_name, cdm.db_user)

    # Cascade delete all dependent records in a single transaction
    try:
        # 1. Delete cohort shares and versions for cohorts in this CDM
        cohort_ids = [c.id for c in db.query(Cohort.id).filter(Cohort.cdm_name == cdm_name).all()]
        if cohort_ids:
            db.query(CohortShare).filter(CohortShare.cohort_id.in_(cohort_ids)).delete(synchronize_session=False)
            db.query(CohortVersion).filter(CohortVersion.cohort_id.in_(cohort_ids)).delete(synchronize_session=False)

        # 2. Delete CDM-scoped entities
        db.query(Cohort).filter(Cohort.cdm_name == cdm_name).delete(synchronize_session=False)
        db.query(AnalysisSnapshot).filter(AnalysisSnapshot.cdm_name == cdm_name).delete(synchronize_session=False)
        db.query(AnalysisSettings).filter(AnalysisSettings.cdm_name == cdm_name).delete(synchronize_session=False)
        db.query(MappingDecision).filter(MappingDecision.cdm_name == cdm_name).delete(synchronize_session=False)
        db.query(CdmAccess).filter(CdmAccess.cdm_name == cdm_name).delete(synchronize_session=False)
        db.query(CdmGroupAccess).filter(CdmGroupAccess.cdm_name == cdm_name).delete(synchronize_session=False)
        db.query(ConceptSet).filter(ConceptSet.cdm_name == cdm_name).delete(synchronize_session=False)
        db.query(IncidenceAnalysis).filter(IncidenceAnalysis.cdm_name == cdm_name).delete(synchronize_session=False)
        db.query(EstimationAnalysis).filter(EstimationAnalysis.cdm_name == cdm_name).delete(synchronize_session=False)
        db.query(SavedQuery).filter(SavedQuery.cdm_name == cdm_name).delete(synchronize_session=False)

        # 3. Delete the CDM config itself
        db.delete(cdm)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to delete CDM '%s' and associated data", cdm_name)
        raise HTTPException(status_code=500, detail="Failed to delete CDM and associated data")
    return {"message": f"CDM '{cdm_name}' and all associated data deleted"}


@router.get("/{cdm_name}/settings")
def get_cdm_settings(cdm_name: str, db: Session = Depends(get_db)):
    """Get analysis settings for a CDM."""
    settings = db.query(AnalysisSettings).filter(AnalysisSettings.cdm_name == cdm_name).first()
    if not settings:
        return {
            "cdm_name": cdm_name,
            "omop_schema": DEFAULT_OMOP_SCHEMA,
            "top_unmapped_terms": 50,
            "top_concepts": 50,
            "max_records_per_person": 100,
            "max_observation_months": 120,
            "comparison_alert_threshold": 5.0,
        }
    return {
        "cdm_name": settings.cdm_name,
        "omop_schema": settings.omop_schema,
        "top_unmapped_terms": settings.top_unmapped_terms,
        "top_concepts": settings.top_concepts,
        "max_records_per_person": settings.max_records_per_person,
        "max_observation_months": settings.max_observation_months,
        "comparison_alert_threshold": settings.comparison_alert_threshold,
    }


@router.put("/{cdm_name}/settings")
def update_cdm_settings(cdm_name: str, req: SettingsUpdateRequest, db: Session = Depends(get_db)):
    """Update analysis settings for a CDM."""
    settings = db.query(AnalysisSettings).filter(AnalysisSettings.cdm_name == cdm_name).first()
    if not settings:
        settings = AnalysisSettings(cdm_name=cdm_name)
        db.add(settings)
        try:
            db.flush()
        except Exception:
            db.rollback()
            settings = db.query(AnalysisSettings).filter(AnalysisSettings.cdm_name == cdm_name).first()

    if req.omop_schema is not None:
        settings.omop_schema = req.omop_schema
    if req.top_unmapped_terms is not None:
        settings.top_unmapped_terms = req.top_unmapped_terms
    if req.top_concepts is not None:
        settings.top_concepts = req.top_concepts
    if req.max_records_per_person is not None:
        settings.max_records_per_person = req.max_records_per_person
    if req.max_observation_months is not None:
        settings.max_observation_months = req.max_observation_months
    if req.comparison_alert_threshold is not None:
        settings.comparison_alert_threshold = req.comparison_alert_threshold

    db.commit()
    return {"message": f"Settings for '{cdm_name}' updated successfully"}
