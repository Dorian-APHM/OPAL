"""
Incidence Rate analysis router.

Computes incidence rates using existing saved cohorts as target and outcome.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.app_db import get_db
from db.models import (
    CdmConfig, Cohort, CohortVersion, AnalysisSettings, IncidenceAnalysis,
)
from db.omop_connector import get_omop_connection
from utils.crypto import decrypt_password
from config import DEFAULT_OMOP_SCHEMA
from modules.cohort.sql_builder import build_cohort_sql
from modules.incidence.engine import build_incidence_sql, compute_incidence

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/incidence", tags=["incidence"])


def _get_cdm_conn(db: Session, cdm_name: str):
    cdm = db.query(CdmConfig).filter(CdmConfig.name == cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{cdm_name}' not found")
    password = decrypt_password(cdm.db_password_encrypted)
    conn = get_omop_connection(cdm.db_host, cdm.db_port, cdm.db_name, cdm.db_user, password)
    settings = db.query(AnalysisSettings).filter(AnalysisSettings.cdm_name == cdm_name).first()
    schema = settings.omop_schema if settings else cdm.omop_schema or DEFAULT_OMOP_SCHEMA
    return conn, schema


def _get_cohort_sql(db: Session, cohort_id: int, omop_schema: str) -> tuple[str, str]:
    """Get the SQL and name for a saved cohort."""
    cohort = db.query(Cohort).filter(Cohort.id == cohort_id).first()
    if not cohort:
        raise HTTPException(status_code=404, detail=f"Cohort {cohort_id} not found")
    version = (
        db.query(CohortVersion)
        .filter(CohortVersion.cohort_id == cohort_id)
        .order_by(CohortVersion.version.desc())
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail=f"No version found for cohort {cohort_id}")
    criteria = version.criteria_json
    # Build SQL that returns person_id, cohort_start_date
    sql = _build_dated_cohort_sql(criteria, omop_schema)
    return sql, cohort.name


def _build_dated_cohort_sql(criteria: dict, omop_schema: str) -> str:
    """
    Build cohort SQL that returns person_id and cohort_start_date.

    Uses the exit_criteria if present, otherwise defaults to end of observation.
    """
    from modules.cohort.sql_builder import build_cohort_sql as _build_sql
    from config import DOMAIN_CONFIG

    base_sql = _build_sql(criteria, omop_schema)

    # Determine the date column from the first inclusion criterion
    inclusion = criteria.get("inclusion", {})
    inc_criteria = inclusion.get("criteria", [])
    date_col = None
    domain_table = None
    pid_col = None
    for c in inc_criteria:
        domain = c.get("domain", "")
        if domain in DOMAIN_CONFIG:
            cfg = DOMAIN_CONFIG[domain]
            date_col = cfg["date_col"]
            domain_table = cfg["table"]
            pid_col = cfg["person_id"]
            break

    if not date_col:
        # Fallback: use observation_period_start_date
        return (
            f"SELECT p.person_id, op.observation_period_start_date AS cohort_start_date\n"
            f"FROM ({base_sql}) p\n"
            f"JOIN {omop_schema}.observation_period op ON p.person_id = op.person_id"
        )

    # Get the exit criteria
    exit_criteria = criteria.get("exit_criteria")
    exit_type = exit_criteria.get("type", "end_of_observation") if exit_criteria else "end_of_observation"

    # Build SQL that returns person_id + cohort_start_date + cohort_end_date
    # First: get cohort_start_date from the earliest event matching the criteria
    dated_sql = (
        f"SELECT base.person_id,\n"
        f"       MIN(t.{date_col}) AS cohort_start_date\n"
        f"FROM ({base_sql}) base\n"
        f"JOIN {omop_schema}.{domain_table} t ON base.person_id = t.{pid_col}\n"
        f"GROUP BY base.person_id"
    )

    return dated_sql


class IncidenceComputeRequest(BaseModel):
    cdm_name: str
    target_cohort_id: int
    outcome_cohort_id: int
    time_at_risk_start: int = 0
    time_at_risk_end: str | int = "observation_end"
    strata: list[str] = []
    age_groups: list[dict] = []
    clean_window: int = 0


class IncidenceSaveRequest(BaseModel):
    cdm_name: str
    name: str
    target_cohort_id: int
    outcome_cohort_id: int
    parameters: dict = {}
    results: dict = {}


@router.post("/compute")
def compute_incidence_rate(body: IncidenceComputeRequest, db=Depends(get_db)):
    conn, omop_schema = _get_cdm_conn(db, body.cdm_name)
    try:
        target_sql, target_name = _get_cohort_sql(db, body.target_cohort_id, omop_schema)
        outcome_sql, outcome_name = _get_cohort_sql(db, body.outcome_cohort_id, omop_schema)

        sql = build_incidence_sql(
            target_sql=target_sql,
            outcome_sql=outcome_sql,
            omop_schema=omop_schema,
            time_at_risk_start=body.time_at_risk_start,
            time_at_risk_end=body.time_at_risk_end,
            strata=body.strata,
            age_groups=body.age_groups,
            clean_window=body.clean_window,
        )

        cur = conn.cursor()
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.close()

        result = compute_incidence(
            rows,
            strata=body.strata,
            age_groups=body.age_groups if body.age_groups else None,
        )
        result["target_name"] = target_name
        result["outcome_name"] = outcome_name
        result["sql"] = sql

        return result
    finally:
        conn.close()


@router.post("/save")
def save_incidence_analysis(body: IncidenceSaveRequest, db=Depends(get_db)):
    analysis = IncidenceAnalysis(
        cdm_name=body.cdm_name,
        name=body.name,
        target_cohort_id=body.target_cohort_id,
        outcome_cohort_id=body.outcome_cohort_id,
        parameters_json=json.dumps(body.parameters),
        results_json=json.dumps(body.results),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return {"id": analysis.id, "name": analysis.name}


@router.get("/")
def list_incidence_analyses(cdm_name: str | None = None, db=Depends(get_db)):
    q = db.query(IncidenceAnalysis)
    if cdm_name:
        q = q.filter(IncidenceAnalysis.cdm_name == cdm_name)
    analyses = q.order_by(IncidenceAnalysis.created_at.desc()).all()
    return {
        "analyses": [
            {
                "id": a.id,
                "cdm_name": a.cdm_name,
                "name": a.name,
                "target_cohort_id": a.target_cohort_id,
                "outcome_cohort_id": a.outcome_cohort_id,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in analyses
        ]
    }


@router.get("/{analysis_id}")
def get_incidence_analysis(analysis_id: int, db=Depends(get_db)):
    a = db.query(IncidenceAnalysis).filter(IncidenceAnalysis.id == analysis_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Incidence analysis not found")
    return {
        "id": a.id,
        "cdm_name": a.cdm_name,
        "name": a.name,
        "target_cohort_id": a.target_cohort_id,
        "outcome_cohort_id": a.outcome_cohort_id,
        "parameters": json.loads(a.parameters_json) if a.parameters_json else {},
        "results": json.loads(a.results_json) if a.results_json else {},
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
