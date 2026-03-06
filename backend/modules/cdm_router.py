"""
CDM management API endpoints — CRUD for CDM connections.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.app_db import get_db
from db.models import CdmConfig, AnalysisSettings
from db.omop_connector import test_omop_connection
from utils.crypto import encrypt_password, decrypt_password
from config import DEFAULT_OMOP_SCHEMA

router = APIRouter(prefix="/api/cdm", tags=["cdm"])


class CdmCreateRequest(BaseModel):
    name: str
    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str
    omop_schema: str = DEFAULT_OMOP_SCHEMA


class CdmTestRequest(BaseModel):
    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str


class CdmUpdateRequest(BaseModel):
    db_host: str | None = None
    db_port: int | None = None
    db_name: str | None = None
    db_user: str | None = None
    db_password: str | None = None
    omop_schema: str | None = None


class SettingsUpdateRequest(BaseModel):
    omop_schema: str | None = None
    top_unmapped_terms: int | None = None
    top_concepts: int | None = None
    max_records_per_person: int | None = None
    max_observation_months: int | None = None
    comparison_alert_threshold: float | None = None


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
def create_cdm(req: CdmCreateRequest, db: Session = Depends(get_db)):
    """Register a new CDM connection."""
    existing = db.query(CdmConfig).filter(CdmConfig.name == req.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"CDM '{req.name}' already exists")

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
    db.commit()
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
def update_cdm(cdm_name: str, req: CdmUpdateRequest, db: Session = Depends(get_db)):
    """Update a CDM connection."""
    cdm = db.query(CdmConfig).filter(CdmConfig.name == cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{cdm_name}' not found")

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

    db.commit()
    return {"message": f"CDM '{cdm_name}' updated successfully"}


@router.delete("/{cdm_name}")
def delete_cdm(cdm_name: str, db: Session = Depends(get_db)):
    """Delete a CDM connection."""
    cdm = db.query(CdmConfig).filter(CdmConfig.name == cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{cdm_name}' not found")

    db.delete(cdm)
    db.commit()
    return {"message": f"CDM '{cdm_name}' deleted"}


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
