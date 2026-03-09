"""
Estimation router — Kaplan-Meier survival analysis.

Uses existing saved cohorts as target (population) and outcome (event).
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.app_db import get_db
from db.models import (
    CdmConfig, Cohort, CohortVersion, AnalysisSettings, EstimationAnalysis,
)
from db.omop_connector import get_omop_connection
from utils.crypto import decrypt_password
from config import DEFAULT_OMOP_SCHEMA, DOMAIN_CONFIG
from modules.cohort.sql_builder import build_cohort_sql
from modules.estimation.survival import compute_km, compute_median_survival, log_rank_test

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/estimation", tags=["estimation"])


def _get_cdm_conn(db: Session, cdm_name: str):
    cdm = db.query(CdmConfig).filter(CdmConfig.name == cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{cdm_name}' not found")
    password = decrypt_password(cdm.db_password_encrypted)
    conn = get_omop_connection(cdm.db_host, cdm.db_port, cdm.db_name, cdm.db_user, password)
    settings = db.query(AnalysisSettings).filter(AnalysisSettings.cdm_name == cdm_name).first()
    schema = settings.omop_schema if settings else cdm.omop_schema or DEFAULT_OMOP_SCHEMA
    return conn, schema


def _get_cohort_criteria(db: Session, cohort_id: int) -> tuple[dict, str]:
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
        raise HTTPException(status_code=404, detail=f"No version for cohort {cohort_id}")
    return version.criteria_json, cohort.name


def _build_km_sql(
    target_criteria: dict,
    outcome_criteria: dict,
    omop_schema: str,
    time_at_risk_end: int | None = None,
    strata: list[str] | None = None,
) -> str:
    """Build SQL to fetch individual-level survival data."""
    target_sql = build_cohort_sql(target_criteria, omop_schema)
    outcome_sql = build_cohort_sql(outcome_criteria, omop_schema)

    # Determine the date column from target's first inclusion criterion
    inclusion = target_criteria.get("inclusion", {})
    inc_criteria = inclusion.get("criteria", [])
    date_col = None
    domain_table = None
    for c in inc_criteria:
        domain = c.get("domain", "")
        if domain in DOMAIN_CONFIG:
            cfg = DOMAIN_CONFIG[domain]
            date_col = cfg["date_col"]
            domain_table = cfg["table"]
            break

    # Same for outcome
    o_inclusion = outcome_criteria.get("inclusion", {})
    o_criteria = o_inclusion.get("criteria", [])
    o_date_col = None
    o_domain_table = None
    for c in o_criteria:
        domain = c.get("domain", "")
        if domain in DOMAIN_CONFIG:
            cfg = DOMAIN_CONFIG[domain]
            o_date_col = cfg["date_col"]
            o_domain_table = cfg["table"]
            break

    # Exit criteria from target cohort
    exit_criteria = target_criteria.get("exit_criteria")
    exit_type = exit_criteria.get("type", "end_of_observation") if exit_criteria else "end_of_observation"

    # TAR end expression
    if time_at_risk_end is not None:
        tar_limit = f"LEAST(op.observation_period_end_date, cohort_start + INTERVAL '{int(time_at_risk_end)} days')"
    else:
        tar_limit = "op.observation_period_end_date"

    if exit_type == "fixed_duration" and exit_criteria:
        duration = int(exit_criteria.get("duration_days", 365))
        tar_limit = f"LEAST(op.observation_period_end_date, cohort_start + INTERVAL '{duration} days')"

    # Build date extraction for target
    if date_col and domain_table:
        target_dated = (
            f"SELECT base.person_id, MIN(t.{date_col}) AS cohort_start\n"
            f"FROM ({target_sql}) base\n"
            f"JOIN {omop_schema}.{domain_table} t ON base.person_id = t.person_id\n"
            f"GROUP BY base.person_id"
        )
    else:
        target_dated = (
            f"SELECT base.person_id, op.observation_period_start_date AS cohort_start\n"
            f"FROM ({target_sql}) base\n"
            f"JOIN {omop_schema}.observation_period op ON base.person_id = op.person_id"
        )

    # Build date extraction for outcome
    if o_date_col and o_domain_table:
        outcome_dated = (
            f"SELECT base.person_id, MIN(t.{o_date_col}) AS outcome_date\n"
            f"FROM ({outcome_sql}) base\n"
            f"JOIN {omop_schema}.{o_domain_table} t ON base.person_id = t.person_id\n"
            f"GROUP BY base.person_id"
        )
    else:
        outcome_dated = (
            f"SELECT base.person_id, NULL::date AS outcome_date\n"
            f"FROM ({outcome_sql}) base"
        )

    # Strata columns
    strata_cols = ""
    strata_select = ""
    if strata:
        col_exprs = []
        for s in strata:
            if s == "gender":
                col_exprs.append("COALESCE(gc.concept_name, 'Unknown') AS gender_name")
            elif s == "age_group":
                col_exprs.append(
                    "CASE "
                    "WHEN EXTRACT(YEAR FROM te.cohort_start::date) - p.year_of_birth < 18 THEN '0-17' "
                    "WHEN EXTRACT(YEAR FROM te.cohort_start::date) - p.year_of_birth < 40 THEN '18-39' "
                    "WHEN EXTRACT(YEAR FROM te.cohort_start::date) - p.year_of_birth < 65 THEN '40-64' "
                    "ELSE '65+' END AS age_group"
                )
        if col_exprs:
            strata_select = ", " + ", ".join(col_exprs)

    sql = f"""
WITH target_entry AS (
    {target_dated}
),
outcome_entry AS (
    {outcome_dated}
),
survival_data AS (
    SELECT
        te.person_id,
        te.cohort_start,
        {tar_limit} AS tar_end,
        oe.outcome_date,
        CASE
            WHEN oe.outcome_date IS NOT NULL
                 AND oe.outcome_date::date >= te.cohort_start::date
                 AND oe.outcome_date::date <= ({tar_limit})::date
            THEN 1 ELSE 0
        END AS had_event,
        CASE
            WHEN oe.outcome_date IS NOT NULL
                 AND oe.outcome_date::date >= te.cohort_start::date
                 AND oe.outcome_date::date <= ({tar_limit})::date
            THEN (oe.outcome_date::date - te.cohort_start::date)::float
            ELSE (({tar_limit})::date - te.cohort_start::date)::float
        END AS time_days
        {strata_select}
    FROM target_entry te
    JOIN {omop_schema}.observation_period op
        ON te.person_id = op.person_id
        AND te.cohort_start BETWEEN op.observation_period_start_date AND op.observation_period_end_date
    JOIN {omop_schema}.person p ON te.person_id = p.person_id
    LEFT JOIN {omop_schema}.concept gc ON p.gender_concept_id = gc.concept_id
    LEFT JOIN outcome_entry oe ON te.person_id = oe.person_id
    WHERE te.cohort_start::date < ({tar_limit})::date
)
SELECT person_id, time_days, had_event
    {"".join(f", {s}_name" if s == "gender" else f", {s}" for s in (strata or []))}
FROM survival_data
WHERE time_days > 0
"""
    return sql


class KaplanMeierRequest(BaseModel):
    cdm_name: str
    target_cohort_id: int
    outcome_cohort_id: int
    time_at_risk_end: int | None = None
    time_unit: str = "days"
    strata: list[str] = []
    confidence_level: float = 0.95


class EstimationSaveRequest(BaseModel):
    cdm_name: str
    name: str
    analysis_type: str = "kaplan_meier"
    target_cohort_id: int
    outcome_cohort_id: int
    parameters: dict = {}
    results: dict = {}


@router.post("/kaplan-meier")
def compute_kaplan_meier(body: KaplanMeierRequest, db=Depends(get_db)):
    conn, omop_schema = _get_cdm_conn(db, body.cdm_name)
    try:
        target_criteria, target_name = _get_cohort_criteria(db, body.target_cohort_id)
        outcome_criteria, outcome_name = _get_cohort_criteria(db, body.outcome_cohort_id)

        sql = _build_km_sql(
            target_criteria=target_criteria,
            outcome_criteria=outcome_criteria,
            omop_schema=omop_schema,
            time_at_risk_end=body.time_at_risk_end,
            strata=body.strata if body.strata else None,
        )

        cur = conn.cursor()
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.close()

        if not rows:
            return {
                "target_name": target_name,
                "outcome_name": outcome_name,
                "overall": [{"time": 0, "survival": 1.0, "ci_lower": 1.0, "ci_upper": 1.0, "at_risk": 0, "events": 0, "censored": 0}],
                "strata": {},
                "log_rank": None,
                "median_survival": None,
                "summary": {"n": 0, "events": 0, "censored": 0},
            }

        # Time unit conversion
        divisor = 1.0
        if body.time_unit == "months":
            divisor = 30.44
        elif body.time_unit == "years":
            divisor = 365.25

        # Convert times
        times = [float(r["time_days"]) / divisor for r in rows]
        events = [int(r["had_event"]) for r in rows]

        # Overall curve
        overall = compute_km(times, events)
        median = compute_median_survival(overall)

        # Stratified curves
        strata_curves = {}
        lr_test = None
        if body.strata:
            # Group by strata
            strata_groups = {}
            strata_col = "gender_name" if "gender" in body.strata else body.strata[0] if body.strata else None
            if strata_col:
                for r, t, e in zip(rows, times, events):
                    key = str(r.get(strata_col, "Unknown"))
                    if key not in strata_groups:
                        strata_groups[key] = ([], [])
                    strata_groups[key][0].append(t)
                    strata_groups[key][1].append(e)

                for key, (t_list, e_list) in sorted(strata_groups.items()):
                    strata_curves[key] = compute_km(t_list, e_list)

                # Log-rank test
                lr_test = log_rank_test(strata_groups)

        total_events = sum(events)
        return {
            "target_name": target_name,
            "outcome_name": outcome_name,
            "overall": overall,
            "strata": strata_curves,
            "log_rank": lr_test,
            "median_survival": round(median, 2) if median is not None else None,
            "time_unit": body.time_unit,
            "summary": {
                "n": len(rows),
                "events": total_events,
                "censored": len(rows) - total_events,
            },
        }
    finally:
        conn.close()


@router.post("/save")
def save_estimation(body: EstimationSaveRequest, db=Depends(get_db)):
    analysis = EstimationAnalysis(
        cdm_name=body.cdm_name,
        name=body.name,
        analysis_type=body.analysis_type,
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
def list_estimations(cdm_name: str | None = None, db=Depends(get_db)):
    q = db.query(EstimationAnalysis)
    if cdm_name:
        q = q.filter(EstimationAnalysis.cdm_name == cdm_name)
    analyses = q.order_by(EstimationAnalysis.created_at.desc()).all()
    return {
        "analyses": [
            {
                "id": a.id,
                "cdm_name": a.cdm_name,
                "name": a.name,
                "analysis_type": a.analysis_type,
                "target_cohort_id": a.target_cohort_id,
                "outcome_cohort_id": a.outcome_cohort_id,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in analyses
        ]
    }


@router.get("/{analysis_id}")
def get_estimation(analysis_id: int, db=Depends(get_db)):
    a = db.query(EstimationAnalysis).filter(EstimationAnalysis.id == analysis_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Estimation analysis not found")
    return {
        "id": a.id,
        "cdm_name": a.cdm_name,
        "name": a.name,
        "analysis_type": a.analysis_type,
        "target_cohort_id": a.target_cohort_id,
        "outcome_cohort_id": a.outcome_cohort_id,
        "parameters": json.loads(a.parameters_json) if a.parameters_json else {},
        "results": json.loads(a.results_json) if a.results_json else {},
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
