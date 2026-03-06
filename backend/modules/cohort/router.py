"""
Cohort module API endpoints.

Provides CRUD for cohorts, concept search, cohort execution (count, preview,
attrition, sampling), and CSV export.
"""
import csv
import io
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from db.app_db import get_db
from db.models import CdmConfig, Cohort, CohortVersion, AnalysisSettings, ReferenceCodebook
from db.omop_connector import get_omop_connection
from utils.crypto import decrypt_password
from config import DEFAULT_OMOP_SCHEMA, DOMAIN_CONFIG
from modules.cohort.sql_builder import (
    build_cohort_sql,
    build_count_sql,
    build_attrition_sql,
    build_sample_sql,
    build_detailed_sample_sql,
    build_export_sql,
)
from modules.cohort.characterization import run_characterization

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cohorts", tags=["cohorts"])


# ──── Request / Response models ────

class CohortCreateRequest(BaseModel):
    cdm_name: str
    name: str
    description: str = ""
    criteria: dict


class CohortUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    criteria: dict | None = None


class CohortCountRequest(BaseModel):
    cdm_name: str
    criteria: dict


class CohortSampleRequest(BaseModel):
    cdm_name: str
    criteria: dict
    limit: int = 10


class ConceptSearchRequest(BaseModel):
    cdm_name: str
    query: str
    domain: str | None = None
    vocabulary_id: str | None = None
    limit: int = 30


# ──── Helpers ────

def _get_omop_schema(db: Session, cdm: CdmConfig) -> str:
    settings = db.query(AnalysisSettings).filter(
        AnalysisSettings.cdm_name == cdm.name
    ).first()
    return settings.omop_schema if settings else cdm.omop_schema or DEFAULT_OMOP_SCHEMA


def _get_cdm_conn(db: Session, cdm_name: str):
    """Get CDM model and open psycopg2 connection. Raises HTTPException on error."""
    cdm = db.query(CdmConfig).filter(CdmConfig.name == cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{cdm_name}' not found")
    password = decrypt_password(cdm.db_password_encrypted)
    try:
        conn = get_omop_connection(cdm.db_host, cdm.db_port, cdm.db_name, cdm.db_user, password)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cannot connect to CDM: {e}")
    return cdm, conn


# ──── Concept Search ────

@router.post("/concepts/search")
def search_concepts(req: ConceptSearchRequest, db: Session = Depends(get_db)):
    """
    Search OMOP concepts by name or code.
    Searches the concept table with ILIKE and returns matching concepts.
    """
    cdm, conn = _get_cdm_conn(db, req.cdm_name)
    schema = _get_omop_schema(db, cdm)

    try:
        from psycopg2.extras import DictCursor
        with conn.cursor(cursor_factory=DictCursor) as cur:
            if req.query.strip().isdigit():
                wheres = ["c.concept_id = %(cid)s"]
                params: dict = {
                    "cid": int(req.query.strip()),
                    "lim": min(req.limit, 100),
                }
            else:
                wheres = [
                    "(c.concept_name ILIKE %(q)s OR c.concept_code ILIKE %(code_q)s)"
                ]
                params: dict = {
                    "q": f"%{req.query}%",
                    "code_q": f"%{req.query}%",
                    "lim": min(req.limit, 100),
                }

            if req.domain:
                wheres.append("c.domain_id = %(domain)s")
                params["domain"] = req.domain

            if req.vocabulary_id:
                wheres.append("c.vocabulary_id = %(vocab)s")
                params["vocab"] = req.vocabulary_id

            where_clause = " AND ".join(wheres)
            sql = f"""
                SELECT c.concept_id, c.concept_name, c.concept_code,
                       c.domain_id, c.vocabulary_id, c.concept_class_id,
                       c.standard_concept
                FROM {schema}.concept c
                WHERE {where_clause}
                  AND c.invalid_reason IS NULL
                ORDER BY
                  CASE WHEN c.standard_concept = 'S' THEN 0 ELSE 1 END,
                  LENGTH(c.concept_name),
                  c.concept_name
                LIMIT %(lim)s
            """
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.exception("Concept search failed")
        raise HTTPException(status_code=500, detail=f"Concept search error: {e}")
    finally:
        conn.close()

    return {"concepts": rows, "count": len(rows)}


@router.get("/concepts/vocabularies")
def list_vocabularies(cdm_name: str, db: Session = Depends(get_db)):
    """List all available vocabularies in the CDM."""
    cdm, conn = _get_cdm_conn(db, cdm_name)
    schema = _get_omop_schema(db, cdm)

    try:
        from psycopg2.extras import DictCursor
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(f"""
                SELECT vocabulary_id, vocabulary_name, vocabulary_version
                FROM {schema}.vocabulary
                ORDER BY vocabulary_id
            """)
            rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vocabulary listing error: {e}")
    finally:
        conn.close()

    return {"vocabularies": rows}


@router.get("/domains")
def list_cohort_domains():
    """List available OMOP domains for cohort criteria."""
    domains = [
        {"name": name, "table": cfg["table"]}
        for name, cfg in DOMAIN_CONFIG.items()
    ]
    return {"domains": domains}


# ──── Cohort CRUD ────

@router.get("/")
def list_cohorts(cdm_name: str | None = None, db: Session = Depends(get_db)):
    """List all cohorts, optionally filtered by CDM."""
    query = db.query(Cohort)
    if cdm_name:
        query = query.filter(Cohort.cdm_name == cdm_name)
    cohorts = query.order_by(Cohort.updated_at.desc()).all()

    result = []
    for c in cohorts:
        latest = (
            db.query(CohortVersion)
            .filter(CohortVersion.cohort_id == c.id)
            .order_by(CohortVersion.version.desc())
            .first()
        )
        result.append({
            "id": c.id,
            "cdm_name": c.cdm_name,
            "name": c.name,
            "description": c.description,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "latest_version": latest.version if latest else 0,
            "patient_count": latest.patient_count if latest else None,
        })
    return {"cohorts": result}


@router.post("/")
def create_cohort(req: CohortCreateRequest, db: Session = Depends(get_db)):
    """Create a new cohort with initial criteria."""
    # Verify CDM exists
    cdm = db.query(CdmConfig).filter(CdmConfig.name == req.cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{req.cdm_name}' not found")

    schema = _get_omop_schema(db, cdm)

    # Generate SQL
    try:
        sql = build_cohort_sql(req.criteria, schema)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid criteria: {e}")

    cohort = Cohort(
        cdm_name=req.cdm_name,
        name=req.name,
        description=req.description,
    )
    db.add(cohort)
    db.flush()  # Get the ID

    version = CohortVersion(
        cohort_id=cohort.id,
        version=1,
        criteria_json=req.criteria,
        generated_sql=sql,
    )
    db.add(version)
    db.commit()
    db.refresh(cohort)
    db.refresh(version)

    return {
        "id": cohort.id,
        "name": cohort.name,
        "version": version.version,
        "generated_sql": sql,
    }


@router.get("/{cohort_id}")
def get_cohort(cohort_id: int, db: Session = Depends(get_db)):
    """Get cohort details with all versions."""
    cohort = db.query(Cohort).filter(Cohort.id == cohort_id).first()
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")

    versions = (
        db.query(CohortVersion)
        .filter(CohortVersion.cohort_id == cohort_id)
        .order_by(CohortVersion.version.desc())
        .all()
    )

    return {
        "id": cohort.id,
        "cdm_name": cohort.cdm_name,
        "name": cohort.name,
        "description": cohort.description,
        "created_at": cohort.created_at.isoformat() if cohort.created_at else None,
        "updated_at": cohort.updated_at.isoformat() if cohort.updated_at else None,
        "versions": [
            {
                "id": v.id,
                "version": v.version,
                "criteria_json": v.criteria_json,
                "generated_sql": v.generated_sql,
                "patient_count": v.patient_count,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in versions
        ],
    }


@router.put("/{cohort_id}")
def update_cohort(cohort_id: int, req: CohortUpdateRequest, db: Session = Depends(get_db)):
    """Update a cohort. If criteria change, creates a new version."""
    cohort = db.query(Cohort).filter(Cohort.id == cohort_id).first()
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")

    if req.name is not None:
        cohort.name = req.name
    if req.description is not None:
        cohort.description = req.description

    new_version = None
    if req.criteria is not None:
        cdm = db.query(CdmConfig).filter(CdmConfig.name == cohort.cdm_name).first()
        schema = _get_omop_schema(db, cdm) if cdm else DEFAULT_OMOP_SCHEMA

        try:
            sql = build_cohort_sql(req.criteria, schema)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid criteria: {e}")

        max_ver = db.query(func.max(CohortVersion.version)).filter(
            CohortVersion.cohort_id == cohort_id
        ).scalar() or 0

        new_version = CohortVersion(
            cohort_id=cohort_id,
            version=max_ver + 1,
            criteria_json=req.criteria,
            generated_sql=sql,
        )
        db.add(new_version)

    cohort.updated_at = datetime.utcnow()
    db.commit()

    return {
        "id": cohort.id,
        "name": cohort.name,
        "new_version": new_version.version if new_version else None,
    }


@router.delete("/{cohort_id}")
def delete_cohort(cohort_id: int, request: Request, db: Session = Depends(get_db)):
    """Delete a cohort and all its versions. Admin/omop-dim only."""
    user = getattr(request.state, "user", {})
    user_roles = user.get("roles", [])
    if not any(r in ("admin", "omop-dim") for r in user_roles):
        raise HTTPException(status_code=403, detail="Only admin and omop-dim can delete cohorts")
    cohort = db.query(Cohort).filter(Cohort.id == cohort_id).first()
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")

    db.query(CohortVersion).filter(CohortVersion.cohort_id == cohort_id).delete()
    db.delete(cohort)
    db.commit()
    return {"deleted": True, "id": cohort_id}


# ──── Cohort Execution ────

@router.post("/count")
def cohort_count(req: CohortCountRequest, db: Session = Depends(get_db)):
    """Execute a cohort definition and return the patient count."""
    cdm, conn = _get_cdm_conn(db, req.cdm_name)
    schema = _get_omop_schema(db, cdm)

    try:
        # Log criteria for debugging operators
        inc_criteria = req.criteria.get("inclusion", {}).get("criteria", [])
        for i, c in enumerate(inc_criteria):
            logger.info("Criterion %d: domain=%s, operatorWithNext=%s", i, c.get("domain"), c.get("operatorWithNext"))
        sql = build_count_sql(req.criteria, schema)
        logger.info("Cohort count SQL: %s", sql[:500])
        from psycopg2.extras import DictCursor
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(sql)
            row = cur.fetchone()
            count = row["patient_count"] if row else 0
    except Exception as e:
        logger.exception("Cohort count failed")
        raise HTTPException(status_code=500, detail=f"Cohort count error: {e}")
    finally:
        conn.close()

    return {"patient_count": count, "sql": sql}


@router.post("/count/approximate")
def cohort_count_approximate(req: CohortCountRequest, db: Session = Depends(get_db)):
    """
    Quick approximate count using TABLESAMPLE.
    Useful for initial iterations before running exact count.
    """
    cdm, conn = _get_cdm_conn(db, req.cdm_name)
    schema = _get_omop_schema(db, cdm)

    try:
        # Get total persons for scaling
        from psycopg2.extras import DictCursor
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM {schema}.person")
            total_persons = cur.fetchone()["n"]

            # Run on a 10% sample
            sample_sql = build_count_sql(req.criteria, schema)
            # Wrap each table reference to use TABLESAMPLE
            cur.execute(sample_sql)
            row = cur.fetchone()
            exact_count = row["patient_count"] if row else 0

        # For now return exact count (TABLESAMPLE optimization to be added later)
        return {
            "patient_count": exact_count,
            "approximate": False,
            "total_persons": total_persons,
        }
    except Exception as e:
        logger.exception("Approximate count failed")
        raise HTTPException(status_code=500, detail=f"Count error: {e}")
    finally:
        conn.close()


@router.post("/attrition")
def cohort_attrition(req: CohortCountRequest, db: Session = Depends(get_db)):
    """
    Run attrition analysis: execute each step incrementally and return
    the patient count at each step.
    """
    cdm, conn = _get_cdm_conn(db, req.cdm_name)
    schema = _get_omop_schema(db, cdm)

    try:
        steps = build_attrition_sql(req.criteria, schema)
        from psycopg2.extras import DictCursor
        results = []
        with conn.cursor(cursor_factory=DictCursor) as cur:
            for step in steps:
                try:
                    cur.execute(step["sql"])
                    row = cur.fetchone()
                    count = row[0] if row else 0
                    results.append({
                        "step": step["step"],
                        "label": step["label"],
                        "count": count,
                    })
                except Exception as e:
                    logger.warning("Attrition step %d failed: %s", step["step"], e)
                    conn.rollback()
                    results.append({
                        "step": step["step"],
                        "label": step["label"],
                        "count": None,
                        "error": str(e),
                    })
    except Exception as e:
        logger.exception("Attrition analysis failed")
        raise HTTPException(status_code=500, detail=f"Attrition error: {e}")
    finally:
        conn.close()

    return {"steps": results}


@router.post("/sample")
def cohort_sample(req: CohortSampleRequest, db: Session = Depends(get_db)):
    """Return a random sample of patients matching the cohort criteria."""
    cdm, conn = _get_cdm_conn(db, req.cdm_name)
    schema = _get_omop_schema(db, cdm)

    try:
        sql = build_sample_sql(req.criteria, schema, limit=req.limit)
        from psycopg2.extras import DictCursor
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(sql)
            patients = [dict(r) for r in cur.fetchall()]
            # Convert dates to strings
            for p in patients:
                for k, v in p.items():
                    if hasattr(v, 'isoformat'):
                        p[k] = v.isoformat()
    except Exception as e:
        logger.exception("Cohort sampling failed")
        raise HTTPException(status_code=500, detail=f"Sampling error: {e}")
    finally:
        conn.close()

    return {"patients": patients, "count": len(patients)}


@router.post("/sample/detailed")
def cohort_sample_detailed(req: CohortSampleRequest, db: Session = Depends(get_db)):
    """Return a detailed patient sample with per-criterion matched codes and values."""
    cdm, conn = _get_cdm_conn(db, req.cdm_name)
    schema = _get_omop_schema(db, cdm)

    try:
        sql, columns_meta = build_detailed_sample_sql(req.criteria, schema, limit=req.limit)
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            patients = [dict(r) for r in cur.fetchall()]
            for p in patients:
                for k, v in p.items():
                    if hasattr(v, 'isoformat'):
                        p[k] = v.isoformat()
                    elif isinstance(v, float) and v != v:  # NaN
                        p[k] = None
    except Exception as e:
        logger.exception("Detailed sampling failed")
        raise HTTPException(status_code=500, detail=f"Detailed sampling error: {e}")
    finally:
        conn.close()

    # Post-process: enrich codes without labels using reference codebooks
    code_cols = [cm["key"] for cm in columns_meta if cm["key"].startswith("crit_") and cm["key"].endswith("_code")]
    if code_cols and patients:
        # Collect all source codes that have no label (no " — " in the value)
        codes_needing_label: set[str] = set()
        for p in patients:
            for col in code_cols:
                val = p.get(col)
                if val and " — " not in str(val):
                    codes_needing_label.add(str(val).strip())

        if codes_needing_label:
            # Lookup in reference_codebooks
            ref_entries = (
                db.query(ReferenceCodebook.code, ReferenceCodebook.description)
                .filter(ReferenceCodebook.code.in_(list(codes_needing_label)))
                .all()
            )
            ref_map = {r.code: r.description for r in ref_entries}

            if ref_map:
                for p in patients:
                    for col in code_cols:
                        val = p.get(col)
                        if val and " — " not in str(val):
                            code = str(val).strip()
                            if code in ref_map:
                                p[col] = f"{code} — {ref_map[code]}"

    return {"patients": patients, "count": len(patients), "columns": columns_meta}


@router.post("/export/direct")
def export_direct(req: CohortCountRequest, db: Session = Depends(get_db)):
    """Export full patient list as CSV directly from criteria (no save required)."""
    cdm, conn = _get_cdm_conn(db, req.cdm_name)
    schema = _get_omop_schema(db, cdm)

    try:
        sql = build_export_sql(req.criteria, schema)
        from psycopg2.extras import DictCursor
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["person_id", "year_of_birth", "gender", "race",
                         "observation_period_start_date", "observation_period_end_date"])
        for row in rows:
            writer.writerow([
                row["person_id"],
                row["year_of_birth"],
                row["gender"],
                row["race"],
                row["observation_period_start_date"].isoformat() if hasattr(row.get("observation_period_start_date"), 'isoformat') else row.get("observation_period_start_date", ""),
                row["observation_period_end_date"].isoformat() if hasattr(row.get("observation_period_end_date"), 'isoformat') else row.get("observation_period_end_date", ""),
            ])
        output.seek(0)
    except Exception as e:
        logger.exception("Direct export failed")
        raise HTTPException(status_code=500, detail=f"Export error: {e}")
    finally:
        conn.close()

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cohort_patients.csv"},
    )


class CharacterizationRequest(BaseModel):
    cdm_name: str
    criteria: dict
    top_n: int = 25


@router.post("/characterize")
def cohort_characterize(req: CharacterizationRequest, db: Session = Depends(get_db)):
    """
    Run Table 1 characterization for a cohort definition.
    Returns demographics, domain prevalence, measurement stats, visit types,
    and observation period statistics.
    """
    cdm, conn = _get_cdm_conn(db, req.cdm_name)
    schema = _get_omop_schema(db, cdm)

    try:
        result = run_characterization(conn, req.criteria, schema, top_n=req.top_n)
    except Exception as e:
        logger.exception("Characterization failed")
        raise HTTPException(status_code=500, detail=f"Characterization error: {e}")
    finally:
        conn.close()

    return result


@router.post("/{cohort_id}/execute")
def execute_cohort(cohort_id: int, db: Session = Depends(get_db)):
    """
    Execute a saved cohort's latest version against its CDM,
    store the patient count in the version record.
    """
    cohort = db.query(Cohort).filter(Cohort.id == cohort_id).first()
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")

    latest = (
        db.query(CohortVersion)
        .filter(CohortVersion.cohort_id == cohort_id)
        .order_by(CohortVersion.version.desc())
        .first()
    )
    if not latest:
        raise HTTPException(status_code=404, detail="No version found")

    cdm, conn = _get_cdm_conn(db, cohort.cdm_name)
    schema = _get_omop_schema(db, cdm)

    try:
        sql = build_count_sql(latest.criteria_json, schema)
        from psycopg2.extras import DictCursor
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(sql)
            row = cur.fetchone()
            count = row["patient_count"] if row else 0
    except Exception as e:
        logger.exception("Cohort execution failed")
        raise HTTPException(status_code=500, detail=f"Execution error: {e}")
    finally:
        conn.close()

    latest.patient_count = count
    db.commit()

    return {
        "cohort_id": cohort.id,
        "version": latest.version,
        "patient_count": count,
    }


@router.get("/{cohort_id}/export")
def export_cohort(
    cohort_id: int,
    format: str = Query(default="csv", description="csv or sql"),
    db: Session = Depends(get_db),
):
    """Export cohort as CSV (patient_ids) or SQL."""
    cohort = db.query(Cohort).filter(Cohort.id == cohort_id).first()
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")

    latest = (
        db.query(CohortVersion)
        .filter(CohortVersion.cohort_id == cohort_id)
        .order_by(CohortVersion.version.desc())
        .first()
    )
    if not latest:
        raise HTTPException(status_code=404, detail="No version found")

    if format == "sql":
        content = latest.generated_sql or ""
        filename = f"cohort_{cohort.name}_v{latest.version}.sql"
        return StreamingResponse(
            iter([content]),
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    # CSV: execute and export patient IDs
    cdm, conn = _get_cdm_conn(db, cohort.cdm_name)
    schema = _get_omop_schema(db, cdm)

    try:
        sql = build_cohort_sql(latest.criteria_json, schema)
        from psycopg2.extras import DictCursor
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["person_id"])
        for row in rows:
            writer.writerow([row["person_id"]])
        output.seek(0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export error: {e}")
    finally:
        conn.close()

    filename = f"cohort_{cohort.name}_v{latest.version}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
