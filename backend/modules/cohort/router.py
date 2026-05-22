"""
Cohort module API endpoints.

Provides CRUD for cohorts, concept search, cohort execution (count, preview,
attrition, sampling), and CSV export.
"""
import csv
import io
import logging
import threading
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from utils.cdm_helper import check_cdm_access
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session
from sqlalchemy import func

from db.app_db import get_db
from db.models import CdmConfig, Cohort, CohortVersion, CohortShare, UserGroupMember, AnalysisSettings, ReferenceCodebook
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
from modules.cohort.comparison import compare_cohorts
from utils.rate_limit import limiter
from utils.notifications import notify

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cohorts", tags=["cohorts"])


# ──── Criteria validation ────

_MAX_CRITERIA_DEPTH = 5
_MAX_CONCEPT_IDS = 10000


def _validate_criteria(criteria: dict, _depth: int = 0) -> dict:
    """Validate cohort criteria structure: limit nesting depth and concept_ids count."""
    if _depth > _MAX_CRITERIA_DEPTH:
        raise ValueError(f"Criteria nesting depth exceeds maximum of {_MAX_CRITERIA_DEPTH}")
    if not isinstance(criteria, dict):
        raise ValueError("Criteria must be a JSON object")

    for group_key in ("inclusion", "exclusion"):
        group = criteria.get(group_key)
        if group is not None:
            if not isinstance(group, dict):
                raise ValueError(f"'{group_key}' must be a JSON object")
            for crit in group.get("criteria", []):
                if not isinstance(crit, dict):
                    raise ValueError(f"Each criterion in '{group_key}' must be a JSON object")
                cids = crit.get("concept_ids", [])
                if not isinstance(cids, list):
                    raise ValueError("concept_ids must be a list")
                if len(cids) > _MAX_CONCEPT_IDS:
                    raise ValueError(f"concept_ids count ({len(cids)}) exceeds maximum of {_MAX_CONCEPT_IDS}")
                for cid in cids:
                    if not isinstance(cid, (int, float)):
                        raise ValueError(f"concept_ids must contain integers, got {type(cid).__name__}")
            for sub_group in group.get("groups", []):
                _validate_criteria({"inclusion": sub_group}, _depth=_depth + 1)

    return criteria


# ──── Request / Response models ────

class CohortCreateRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    criteria: dict

    @field_validator("criteria")
    @classmethod
    def validate_criteria(cls, v: dict) -> dict:
        return _validate_criteria(v)


class CohortUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    criteria: dict | None = None

    @field_validator("criteria")
    @classmethod
    def validate_criteria(cls, v: dict | None) -> dict | None:
        if v is not None:
            return _validate_criteria(v)
        return v


class CohortCountRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1, max_length=255)
    criteria: dict

    @field_validator("criteria")
    @classmethod
    def validate_criteria(cls, v: dict) -> dict:
        return _validate_criteria(v)


class CohortSampleRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1, max_length=255)
    criteria: dict
    limit: int = Field(default=10, ge=1, le=1000)

    @field_validator("criteria")
    @classmethod
    def validate_criteria(cls, v: dict) -> dict:
        return _validate_criteria(v)


class ConceptSearchRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1, max_length=255)
    query: str = Field(..., min_length=1, max_length=500)
    domain: str | None = Field(default=None, max_length=100)
    vocabulary_id: str | None = Field(default=None, max_length=100)
    standard_only: bool = False
    limit: int = Field(default=30, ge=1, le=200)


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
        logger.exception("Cannot connect to CDM '%s'", cdm.name)
        raise HTTPException(status_code=502, detail="Cannot connect to CDM database")
    return cdm, conn


# ──── Concept Search ────

@router.post("/concepts/search")
def search_concepts(req: ConceptSearchRequest, request: Request, db: Session = Depends(get_db)):
    """
    Search OMOP concepts by name or code.
    Searches the concept table with ILIKE and returns matching concepts.
    """
    check_cdm_access(request, req.cdm_name)
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
                    "(unaccent(c.concept_name) ILIKE unaccent(%(q)s) OR unaccent(c.concept_code) ILIKE unaccent(%(code_q)s))"
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

            if req.standard_only:
                wheres.append("c.standard_concept = 'S'")

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
        raise HTTPException(status_code=500, detail="An internal error occurred during concept search")
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
        logger.exception("Vocabulary listing failed")
        raise HTTPException(status_code=500, detail="An internal error occurred while listing vocabularies")
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
def list_cohorts(cdm_name: str | None = None, request: Request = None, db: Session = Depends(get_db)):
    """List cohorts visible to the current user.

    - admin / data-manager: see all cohorts.
    - Others: see own cohorts + shared with them (by user, group, or public).
    """
    user = getattr(request.state, "user", {}) if request else {}
    username = user.get("preferred_username", "")
    user_roles = user.get("roles", [])
    is_privileged = any(r in ("admin", "data-manager") for r in user_roles)

    query = db.query(Cohort)
    if cdm_name:
        query = query.filter(Cohort.cdm_name == cdm_name)

    if not is_privileged and username:
        # User's own groups
        user_groups = [
            row.group_name for row in
            db.query(UserGroupMember.group_name).filter(UserGroupMember.username == username).all()
        ]

        # Cohort IDs shared with this user directly or via groups
        share_q = db.query(CohortShare.cohort_id).filter(
            ((CohortShare.share_type == "user") & (CohortShare.share_target == username))
        )
        if user_groups:
            share_q = share_q.union(
                db.query(CohortShare.cohort_id).filter(
                    (CohortShare.share_type == "group") & (CohortShare.share_target.in_(user_groups))
                )
            )
        shared_ids = [row[0] for row in share_q.all()]

        # Own + shared + public
        query = query.filter(
            (Cohort.created_by == username)
            | (Cohort.shared_with_all == 1)
            | (Cohort.id.in_(shared_ids) if shared_ids else False)
        )

    cohorts = query.order_by(Cohort.updated_at.desc()).all()

    # P48 fix: fetch latest versions for all cohorts in a single query
    cohort_ids = [c.id for c in cohorts]
    latest_versions_map: dict[int, tuple] = {}
    if cohort_ids:
        from sqlalchemy import and_
        # Subquery: max version per cohort
        max_ver_sq = (
            db.query(CohortVersion.cohort_id, func.max(CohortVersion.version).label("max_ver"))
            .filter(CohortVersion.cohort_id.in_(cohort_ids))
            .group_by(CohortVersion.cohort_id)
            .subquery()
        )
        latest_rows = (
            db.query(CohortVersion)
            .join(max_ver_sq, and_(
                CohortVersion.cohort_id == max_ver_sq.c.cohort_id,
                CohortVersion.version == max_ver_sq.c.max_ver,
            ))
            .all()
        )
        for lv in latest_rows:
            latest_versions_map[lv.cohort_id] = (lv.version, lv.patient_count)

    result = []
    for c in cohorts:
        ver, pcount = latest_versions_map.get(c.id, (0, None))
        result.append({
            "id": c.id,
            "cdm_name": c.cdm_name,
            "name": c.name,
            "description": c.description,
            "created_by": c.created_by,
            "shared_with_all": bool(c.shared_with_all),
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "latest_version": ver,
            "patient_count": pcount,
        })
    return {"cohorts": result}


@router.post("/")
def create_cohort(req: CohortCreateRequest, request: Request, db: Session = Depends(get_db)):
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

    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "system")

    cohort = Cohort(
        cdm_name=req.cdm_name,
        name=req.name,
        description=req.description,
        created_by=username,
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


def _can_access_cohort(db: Session, cohort: Cohort, username: str, user_roles: list) -> bool:
    """Check if a user can access a cohort."""
    if any(r in ("admin", "data-manager") for r in user_roles):
        return True
    if cohort.created_by == username:
        return True
    if cohort.shared_with_all:
        return True
    # Shared directly with user?
    direct = db.query(CohortShare).filter(
        CohortShare.cohort_id == cohort.id,
        CohortShare.share_type == "user",
        CohortShare.share_target == username,
    ).first()
    if direct:
        return True
    # Shared via group?
    user_groups = [
        row.group_name for row in
        db.query(UserGroupMember.group_name).filter(UserGroupMember.username == username).all()
    ]
    if user_groups:
        group_share = db.query(CohortShare).filter(
            CohortShare.cohort_id == cohort.id,
            CohortShare.share_type == "group",
            CohortShare.share_target.in_(user_groups),
        ).first()
        if group_share:
            return True
    return False


@router.get("/{cohort_id}")
def get_cohort(cohort_id: int, request: Request, db: Session = Depends(get_db)):
    """Get cohort details with all versions."""
    cohort = db.query(Cohort).filter(Cohort.id == cohort_id).first()
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")

    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "")
    user_roles = user.get("roles", [])
    if not _can_access_cohort(db, cohort, username, user_roles):
        raise HTTPException(status_code=403, detail="You do not have access to this cohort")

    versions = (
        db.query(CohortVersion)
        .filter(CohortVersion.cohort_id == cohort_id)
        .order_by(CohortVersion.version.desc())
        .all()
    )

    shares = db.query(CohortShare).filter(CohortShare.cohort_id == cohort_id).all()

    return {
        "id": cohort.id,
        "cdm_name": cohort.cdm_name,
        "name": cohort.name,
        "description": cohort.description,
        "created_by": cohort.created_by,
        "shared_with_all": bool(cohort.shared_with_all),
        "shares": [
            {"type": s.share_type, "target": s.share_target, "shared_by": s.shared_by}
            for s in shares
        ],
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
def update_cohort(cohort_id: int, req: CohortUpdateRequest, request: Request, db: Session = Depends(get_db)):
    """Update a cohort. If criteria change, creates a new version."""
    cohort = db.query(Cohort).filter(Cohort.id == cohort_id).first()
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")

    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "")
    user_roles = user.get("roles", [])
    if not _can_access_cohort(db, cohort, username, user_roles):
        raise HTTPException(status_code=403, detail="You do not have access to this cohort")

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

    cohort.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "id": cohort.id,
        "name": cohort.name,
        "new_version": new_version.version if new_version else None,
    }


@router.delete("/{cohort_id}")
def delete_cohort(cohort_id: int, request: Request, db: Session = Depends(get_db)):
    """Delete a cohort and all its versions. Owner, admin, or data-manager only."""
    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "")
    user_roles = user.get("roles", [])
    cohort = db.query(Cohort).filter(Cohort.id == cohort_id).first()
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")

    is_privileged = any(r in ("admin", "data-manager") for r in user_roles)
    is_owner = cohort.created_by == username
    if not is_privileged and not is_owner:
        raise HTTPException(status_code=403, detail="Only the owner, admin, or data-manager can delete cohorts")

    # Notify users who had this cohort shared with them
    shares = db.query(CohortShare).filter(CohortShare.cohort_id == cohort_id).all()
    for s in shares:
        if s.share_type == "user" and s.share_target != username:
            notify(
                db, s.share_target, "cohort_deleted",
                title=f"Cohorte supprimée : {cohort.name}",
                message=f"{username} a supprimé la cohorte « {cohort.name} ».",
                link="/cohorts",
                item_id=str(cohort_id),
            )
        elif s.share_type == "group":
            members = db.query(UserGroupMember).filter(UserGroupMember.group_name == s.share_target).all()
            for m in members:
                if m.username != username:
                    notify(
                        db, m.username, "cohort_deleted",
                        title=f"Cohorte supprimée : {cohort.name}",
                        message=f"{username} a supprimé la cohorte « {cohort.name} ».",
                        link="/cohorts",
                        item_id=str(cohort_id),
                    )

    db.query(CohortShare).filter(CohortShare.cohort_id == cohort_id).delete()
    db.query(CohortVersion).filter(CohortVersion.cohort_id == cohort_id).delete()
    db.delete(cohort)
    db.commit()
    return {"deleted": True, "id": cohort_id}


# ──── Cohort Execution ────

@router.post("/count")
def cohort_count(req: CohortCountRequest, request: Request, db: Session = Depends(get_db)):
    """Execute a cohort definition and return the patient count."""
    check_cdm_access(request, req.cdm_name)
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
        raise HTTPException(status_code=500, detail="An internal error occurred during cohort count")
    finally:
        conn.close()

    return {"patient_count": count}


@router.post("/count/approximate")
def cohort_count_approximate(req: CohortCountRequest, request: Request, db: Session = Depends(get_db)):
    """
    Quick approximate count using TABLESAMPLE.
    Useful for initial iterations before running exact count.
    """
    check_cdm_access(request, req.cdm_name)
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
        raise HTTPException(status_code=500, detail="An internal error occurred during count")
    finally:
        conn.close()


@router.post("/attrition")
def cohort_attrition(req: CohortCountRequest, request: Request, db: Session = Depends(get_db)):
    """
    Run attrition analysis: execute each step incrementally and return
    the patient count at each step.
    """
    check_cdm_access(request, req.cdm_name)
    cdm, conn = _get_cdm_conn(db, req.cdm_name)
    schema = _get_omop_schema(db, cdm)

    try:
        steps = build_attrition_sql(req.criteria, schema)
        from psycopg2.extras import DictCursor

        # Build a single CTE-based query for all steps to reduce round-trips
        if len(steps) > 1:
            cte_parts = []
            for i, step in enumerate(steps):
                cte_parts.append(f"step_{i} AS ({step['sql']})")
            cte_query = "WITH " + ", ".join(cte_parts) + " SELECT " + ", ".join(
                f"(SELECT * FROM step_{i}) AS count_{i}" for i in range(len(steps))
            )
            results = []
            with conn.cursor(cursor_factory=DictCursor) as cur:
                try:
                    cur.execute(cte_query)
                    row = cur.fetchone()
                    for i, step in enumerate(steps):
                        count = row[i] if row else None
                        results.append({
                            "step": step["step"],
                            "label": step["label"],
                            "count": count,
                        })
                except Exception:
                    # Fallback to individual queries if CTE fails
                    logger.debug("CTE attrition failed, falling back to individual queries", exc_info=True)
                    conn.rollback()
                    results = []
                    for step in steps:
                        try:
                            cur.execute(step["sql"])
                            row = cur.fetchone()
                            count = row[0] if row else 0
                            results.append({"step": step["step"], "label": step["label"], "count": count})
                        except Exception as e:
                            logger.warning("Attrition step %d failed: %s", step["step"], e)
                            conn.rollback()
                            results.append({"step": step["step"], "label": step["label"], "count": None, "error": "An internal error occurred"})
        else:
            results = []
            with conn.cursor(cursor_factory=DictCursor) as cur:
                for step in steps:
                    try:
                        cur.execute(step["sql"])
                        row = cur.fetchone()
                        count = row[0] if row else 0
                        results.append({"step": step["step"], "label": step["label"], "count": count})
                    except Exception as e:
                        logger.warning("Attrition step %d failed: %s", step["step"], e)
                        conn.rollback()
                        results.append({"step": step["step"], "label": step["label"], "count": None, "error": "An internal error occurred"})
    except Exception as e:
        logger.exception("Attrition analysis failed")
        raise HTTPException(status_code=500, detail="An internal error occurred during attrition analysis")
    finally:
        conn.close()

    return {"steps": results}


@router.post("/sample")
def cohort_sample(req: CohortSampleRequest, request: Request, db: Session = Depends(get_db)):
    """Return a random sample of patients matching the cohort criteria."""
    check_cdm_access(request, req.cdm_name)
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
        raise HTTPException(status_code=500, detail="An internal error occurred during sampling")
    finally:
        conn.close()

    return {"patients": patients, "count": len(patients)}


@router.post("/sample/detailed")
def cohort_sample_detailed(req: CohortSampleRequest, request: Request, db: Session = Depends(get_db)):
    """Return a detailed patient sample with per-criterion matched codes and values."""
    check_cdm_access(request, req.cdm_name)
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
        raise HTTPException(status_code=500, detail="An internal error occurred during detailed sampling")
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
def export_direct(req: CohortCountRequest, request: Request, db: Session = Depends(get_db)):
    """Export full patient list as CSV directly from criteria (no save required)."""
    check_cdm_access(request, req.cdm_name)
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
        raise HTTPException(status_code=500, detail="An internal error occurred during export")
    finally:
        conn.close()

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cohort_patients.csv"},
    )


class RawSqlRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1, max_length=255)
    sql: str = Field(..., min_length=1, max_length=50000)
    limit: int = Field(default=1000, ge=1, le=10000)


@router.get("/sql/schema")
def get_sql_schema(cdm_name: str, db: Session = Depends(get_db)):
    """Return table and column names from the CDM schema for SQL autocompletion."""
    cdm, conn = _get_cdm_conn(db, cdm_name)
    schema = cdm.omop_schema or DEFAULT_OMOP_SCHEMA
    try:
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s
                ORDER BY table_name, ordinal_position
                """,
                [schema],
            )
            rows = cur.fetchall()
        tables: dict[str, list[str]] = {}
        for r in rows:
            tbl = r["table_name"]
            if tbl not in tables:
                tables[tbl] = []
            tables[tbl].append(r["column_name"])
        return {"schema": schema, "tables": tables}
    finally:
        conn.close()


@router.post("/sql/execute")
@limiter.limit("10/minute")
def execute_raw_sql(req: RawSqlRequest, request: Request, db: Session = Depends(get_db)):
    """
    Execute a raw read-only SQL query against a CDM.
    Only SELECT statements are allowed.
    """
    check_cdm_access(request, req.cdm_name)
    import re
    sql_stripped = req.sql.strip().rstrip(";")

    # Only allow SELECT statements (block DML/DDL)
    first_keyword = re.split(r"\s+", sql_stripped, maxsplit=1)[0].upper()
    if first_keyword not in ("SELECT", "WITH", "EXPLAIN"):
        raise HTTPException(
            status_code=400,
            detail="Only SELECT, WITH (CTE), and EXPLAIN queries are allowed",
        )

    # Block dangerous keywords anywhere in the query
    sql_upper = sql_stripped.upper()
    blocked = ["INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE ",
                "TRUNCATE ", "GRANT ", "REVOKE ", "COPY ", "\\\\"]
    for kw in blocked:
        if kw in sql_upper:
            raise HTTPException(
                status_code=400,
                detail=f"Forbidden keyword detected: {kw.strip()}",
            )

    cdm, conn = _get_cdm_conn(db, req.cdm_name)

    # Wrap in a read-only transaction for safety
    try:
        conn.set_session(readonly=True, autocommit=False)
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Apply LIMIT if not already present
            if "LIMIT" not in sql_upper:
                final_sql = f"{sql_stripped}\nLIMIT {req.limit}"
            else:
                final_sql = sql_stripped
            cur.execute(final_sql)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = [dict(r) for r in cur.fetchall()]
            # Convert non-serializable types
            for row in rows:
                for k, v in row.items():
                    if hasattr(v, 'isoformat'):
                        row[k] = v.isoformat()
                    elif isinstance(v, (bytes, memoryview)):
                        row[k] = str(v)
    except Exception as e:
        logger.exception("Raw SQL execution failed")
        raise HTTPException(status_code=500, detail="An internal error occurred during SQL execution")
    finally:
        conn.close()

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": len(rows) >= req.limit,
    }


@router.post("/sql/export")
def export_raw_sql(req: RawSqlRequest, request: Request, db: Session = Depends(get_db)):
    """Execute a raw SQL query and return results as CSV."""
    check_cdm_access(request, req.cdm_name)
    import re
    sql_stripped = req.sql.strip().rstrip(";")

    first_keyword = re.split(r"\s+", sql_stripped, maxsplit=1)[0].upper()
    if first_keyword not in ("SELECT", "WITH"):
        raise HTTPException(status_code=400, detail="Only SELECT/WITH queries allowed")

    sql_upper = sql_stripped.upper()
    blocked = ["INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE ",
                "TRUNCATE ", "GRANT ", "REVOKE ", "COPY ", "\\\\"]
    for kw in blocked:
        if kw in sql_upper:
            raise HTTPException(status_code=400, detail=f"Forbidden keyword: {kw.strip()}")

    cdm, conn = _get_cdm_conn(db, req.cdm_name)

    try:
        conn.set_session(readonly=True, autocommit=False)
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql_stripped)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = cur.fetchall()
    except Exception as e:
        logger.exception("SQL query execution failed")
        raise HTTPException(status_code=500, detail="An internal error occurred during SQL execution")
    finally:
        conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([
            v.isoformat() if hasattr(v, 'isoformat') else v
            for v in (row[c] for c in columns)
        ])
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sql_export.csv"},
    )


class CharacterizationRequest(BaseModel):
    cdm_name: str
    criteria: dict
    top_n: int = 25
    visit_level: bool = False


# ──── Background characterization task tracking ────
_active_characterizations: dict[str, dict] = {}
_characterizations_lock = threading.Lock()


@router.post("/characterize")
@limiter.limit("3/minute")
def cohort_characterize(req: CharacterizationRequest, request: Request, db: Session = Depends(get_db)):
    """
    Launch Table 1 characterization as a background task.
    Returns a task_id for polling via /characterize/status/{task_id}.
    """
    cdm, conn = _get_cdm_conn(db, req.cdm_name)
    schema = _get_omop_schema(db, cdm)

    task_id = str(uuid.uuid4())
    with _characterizations_lock:
        _active_characterizations[task_id] = {
            "status": "running",
            "cdm_name": req.cdm_name,
            "cohort_id": None,
            "result": None,
            "error": None,
            "completed": 0,
            "total": 0,
            "current_step": "",
        }

    def _progress(completed: int, total: int, step_label: str):
        with _characterizations_lock:
            task = _active_characterizations.get(task_id)
            if task:
                task["completed"] = completed
                task["total"] = total
                task["current_step"] = step_label

    def _worker():
        try:
            result = run_characterization(
                conn, req.criteria, schema, top_n=req.top_n,
                visit_level=req.visit_level,
                progress_callback=_progress,
            )
            with _characterizations_lock:
                _active_characterizations[task_id]["result"] = result
                _active_characterizations[task_id]["status"] = "completed"
        except Exception as e:
            logger.exception("Characterization failed")
            with _characterizations_lock:
                _active_characterizations[task_id]["error"] = "An internal error occurred during characterization"
                _active_characterizations[task_id]["status"] = "error"
        finally:
            conn.close()

    from utils.thread_pool import submit_task
    submit_task(_worker)

    return {"task_id": task_id, "status": "running"}


@router.get("/characterize/status/{task_id}")
def characterize_status(task_id: str):
    """Poll the status of a characterization task."""
    with _characterizations_lock:
        task = _active_characterizations.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    resp: dict = {
        "task_id": task_id,
        "status": task["status"],
        "completed": task.get("completed", 0),
        "total": task.get("total", 0),
        "current_step": task.get("current_step", ""),
    }
    if task["status"] == "completed":
        resp["result"] = task["result"]
        # Clean up after delivering results
        with _characterizations_lock:
            _active_characterizations.pop(task_id, None)
    elif task["status"] == "error":
        resp["error"] = task["error"]
        with _characterizations_lock:
            _active_characterizations.pop(task_id, None)
    return resp


@router.post("/characterize/cancel/{task_id}")
def characterize_cancel(task_id: str):
    """Cancel/clean up a characterization task."""
    with _characterizations_lock:
        task = _active_characterizations.pop(task_id, None)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "cancelled"}


@router.get("/characterize/active")
def characterize_active():
    """Return any currently running characterization task."""
    with _characterizations_lock:
        items = list(_active_characterizations.items())
    for tid, task in items:
        if task["status"] == "running":
            return {"task_id": tid, "status": "running", "cdm_name": task["cdm_name"]}
    return {"task_id": None, "status": "none"}


# ──── Pathways Analysis ────

class PathwaysEventCohort(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    domain: str = Field(..., min_length=1, max_length=100)
    concept_ids: list[int] = Field(default_factory=list)
    include_descendants: bool = False
    source_codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_concepts_or_sources(self):
        if not self.concept_ids and not self.source_codes:
            raise ValueError("At least one of concept_ids or source_codes is required")
        return self


class PathwaysRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1, max_length=255)
    criteria: dict
    event_cohorts: list[PathwaysEventCohort] = Field(..., min_length=1, max_length=20)
    max_depth: int = Field(default=5, ge=1, le=10)
    min_cell_count: int = Field(default=5, ge=1, le=1000)
    combo_window: int = Field(default=0, ge=0, le=365)


_active_pathways: dict[str, dict] = {}
_pathways_lock = threading.Lock()


@router.post("/pathways")
@limiter.limit("3/minute")
def cohort_pathways(req: PathwaysRequest, request: Request, db: Session = Depends(get_db)):
    """
    Launch a pathways analysis as a background task.
    Returns a task_id for polling via /pathways/status/{task_id}.
    """
    from modules.cohort.pathways import run_pathways_analysis

    cdm, conn = _get_cdm_conn(db, req.cdm_name)
    schema = _get_omop_schema(db, cdm)

    task_id = str(uuid.uuid4())
    with _pathways_lock:
        _active_pathways[task_id] = {
            "status": "running",
            "cdm_name": req.cdm_name,
            "result": None,
            "error": None,
            "completed": 0,
            "total": 0,
            "current_step": "",
        }

    def _progress(completed: int, total: int, step_label: str):
        with _pathways_lock:
            task = _active_pathways.get(task_id)
            if task:
                task["completed"] = completed
                task["total"] = total
                task["current_step"] = step_label

    def _worker():
        try:
            result = run_pathways_analysis(
                conn,
                req.criteria,
                [ec.model_dump() for ec in req.event_cohorts],
                schema,
                max_depth=req.max_depth,
                min_cell_count=req.min_cell_count,
                combo_window=req.combo_window,
                progress_callback=_progress,
            )
            with _pathways_lock:
                _active_pathways[task_id]["result"] = result
                _active_pathways[task_id]["status"] = "completed"
        except Exception as e:
            logger.exception("Pathways analysis failed")
            with _pathways_lock:
                _active_pathways[task_id]["error"] = "An internal error occurred during pathways analysis"
                _active_pathways[task_id]["status"] = "error"
        finally:
            conn.close()

    from utils.thread_pool import submit_task
    submit_task(_worker)

    return {"task_id": task_id, "status": "running"}


@router.get("/pathways/status/{task_id}")
def pathways_status(task_id: str):
    """Poll the status of a pathways analysis task."""
    with _pathways_lock:
        task = _active_pathways.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    resp: dict = {
        "task_id": task_id,
        "status": task["status"],
        "completed": task.get("completed", 0),
        "total": task.get("total", 0),
        "current_step": task.get("current_step", ""),
    }
    if task["status"] == "completed":
        resp["result"] = task["result"]
        with _pathways_lock:
            _active_pathways.pop(task_id, None)
    elif task["status"] == "error":
        resp["error"] = task["error"]
        with _pathways_lock:
            _active_pathways.pop(task_id, None)
    return resp


@router.post("/pathways/cancel/{task_id}")
def pathways_cancel(task_id: str):
    """Cancel/clean up a pathways analysis task."""
    with _pathways_lock:
        task = _active_pathways.pop(task_id, None)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "cancelled"}


class CohortCompareRequest(BaseModel):
    cdm_name: str
    cohort_id_a: int
    cohort_id_b: int
    visit_level: bool = False


@router.post("/compare")
def compare_cohorts_endpoint(req: CohortCompareRequest, db: Session = Depends(get_db)):
    """
    Compare two saved cohorts using their characterization results.
    Computes SMD (Standardized Mean Difference) for every variable.
    If a cohort has no saved characterization, runs it on-the-fly.
    """
    # Load both cohorts
    cohort_a = db.query(Cohort).filter(Cohort.id == req.cohort_id_a).first()
    if not cohort_a:
        raise HTTPException(status_code=404, detail=f"Cohort A (id={req.cohort_id_a}) not found")
    cohort_b = db.query(Cohort).filter(Cohort.id == req.cohort_id_b).first()
    if not cohort_b:
        raise HTTPException(status_code=404, detail=f"Cohort B (id={req.cohort_id_b}) not found")

    # Verify both belong to the requested CDM
    for label, cohort in [("A", cohort_a), ("B", cohort_b)]:
        if cohort.cdm_name != req.cdm_name:
            raise HTTPException(
                status_code=400,
                detail=f"Cohort {label} belongs to CDM '{cohort.cdm_name}', not '{req.cdm_name}'",
            )

    # Get latest versions
    ver_a = (
        db.query(CohortVersion)
        .filter(CohortVersion.cohort_id == req.cohort_id_a)
        .order_by(CohortVersion.version.desc())
        .first()
    )
    ver_b = (
        db.query(CohortVersion)
        .filter(CohortVersion.cohort_id == req.cohort_id_b)
        .order_by(CohortVersion.version.desc())
        .first()
    )
    if not ver_a or not ver_b:
        raise HTTPException(status_code=404, detail="No version found for one of the cohorts")

    # Get characterization for each, running on-the-fly if needed
    char_a = ver_a.characterization_json
    char_b = ver_b.characterization_json

    # When visit_level is requested, always re-run characterization
    # (saved results may be patient-level)
    force_rerun = req.visit_level
    conn = None
    if not char_a or not char_b or force_rerun:
        cdm, conn = _get_cdm_conn(db, req.cdm_name)
        schema = _get_omop_schema(db, cdm)
        try:
            if not char_a or force_rerun:
                char_a = run_characterization(
                    conn, ver_a.criteria_json, schema,
                    visit_level=req.visit_level,
                )
                if not req.visit_level:
                    ver_a.characterization_json = char_a
                    ver_a.characterized_at = datetime.now(timezone.utc)
            if not char_b or force_rerun:
                char_b = run_characterization(
                    conn, ver_b.criteria_json, schema,
                    visit_level=req.visit_level,
                )
                if not req.visit_level:
                    ver_b.characterization_json = char_b
                    ver_b.characterized_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as e:
            logger.exception("On-the-fly characterization failed during comparison")
            raise HTTPException(status_code=500, detail="An internal error occurred during characterization")
        finally:
            conn.close()

    result = compare_cohorts(char_a, char_b)
    result["cohort_a_name"] = cohort_a.name
    result["cohort_b_name"] = cohort_b.name
    return result


@router.put("/{cohort_id}/characterization")
def save_characterization(cohort_id: int, payload: dict, request: Request, db: Session = Depends(get_db)):
    """Save characterization results to the latest version of a cohort."""
    cohort = db.query(Cohort).filter(Cohort.id == cohort_id).first()
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")

    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "")
    user_roles = user.get("roles", [])
    if not _can_access_cohort(db, cohort, username, user_roles):
        raise HTTPException(status_code=403, detail="You do not have access to this cohort")

    latest = (
        db.query(CohortVersion)
        .filter(CohortVersion.cohort_id == cohort_id)
        .order_by(CohortVersion.version.desc())
        .first()
    )
    if not latest:
        raise HTTPException(status_code=404, detail="No version found")

    latest.characterization_json = payload.get("characterization")
    latest.characterized_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "saved", "cohort_id": cohort_id, "version": latest.version}


@router.get("/{cohort_id}/characterization")
def get_characterization(cohort_id: int, db: Session = Depends(get_db)):
    """Get saved characterization results from the latest version of a cohort."""
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

    return {
        "characterization": latest.characterization_json,
        "characterized_at": latest.characterized_at.isoformat() if latest.characterized_at else None,
        "version": latest.version,
    }


@router.put("/{cohort_id}/pathways-result")
def save_pathways_result(cohort_id: int, payload: dict, request: Request, db: Session = Depends(get_db)):
    """Save pathways analysis results to the latest version of a cohort."""
    cohort = db.query(Cohort).filter(Cohort.id == cohort_id).first()
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")

    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "")
    user_roles = user.get("roles", [])
    if not _can_access_cohort(db, cohort, username, user_roles):
        raise HTTPException(status_code=403, detail="You do not have access to this cohort")

    latest = (
        db.query(CohortVersion)
        .filter(CohortVersion.cohort_id == cohort_id)
        .order_by(CohortVersion.version.desc())
        .first()
    )
    if not latest:
        raise HTTPException(status_code=404, detail="No version found")

    latest.pathways_json = payload.get("pathways")
    latest.pathways_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "saved", "cohort_id": cohort_id, "version": latest.version}


@router.get("/{cohort_id}/pathways-result")
def get_pathways_result(cohort_id: int, db: Session = Depends(get_db)):
    """Get saved pathways analysis results from the latest version of a cohort."""
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

    return {
        "pathways": latest.pathways_json,
        "pathways_at": latest.pathways_at.isoformat() if latest.pathways_at else None,
        "version": latest.version,
    }


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
        raise HTTPException(status_code=500, detail="An internal error occurred during cohort execution")
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

    # CSV: export patient IDs (+ visit_occurrence_id when sameVisit)
    cdm, conn = _get_cdm_conn(db, cohort.cdm_name)
    schema = _get_omop_schema(db, cdm)
    has_same_visit = bool(
        latest.criteria_json.get("inclusion", {}).get("sameVisit", False)
    )

    try:
        sql = build_cohort_sql(latest.criteria_json, schema, include_visit_id=has_same_visit)
        from psycopg2.extras import DictCursor
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        if has_same_visit:
            writer.writerow(["person_id", "visit_occurrence_id"])
            for row in rows:
                writer.writerow([row["person_id"], row["visit_occurrence_id"]])
        else:
            writer.writerow(["person_id"])
            for row in rows:
                writer.writerow([row["person_id"]])
        output.seek(0)
    except Exception as e:
        logger.exception("Cohort export failed")
        raise HTTPException(status_code=500, detail="An internal error occurred during export")
    finally:
        conn.close()

    filename = f"cohort_{cohort.name}_v{latest.version}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ──── Patient Journey ────

@router.get("/patient/{person_id}/journey")
def patient_journey(
    person_id: int,
    cdm_name: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    """
    Return the full clinical timeline for a single patient across all OMOP domains.
    Events are returned grouped by domain, each with date, concept_id, concept_name,
    and source_value.  The frontend renders these on a horizontal timeline.
    """
    cdm, conn = _get_cdm_conn(db, cdm_name)
    schema = _get_omop_schema(db, cdm)

    # End-date columns for domains that have them
    _end_date = {
        "Condition": "condition_end_date",
        "Drug": "drug_exposure_end_date",
        "Visit": "visit_end_date",
        "Device": "device_exposure_end_date",
    }

    # Extra value columns worth fetching
    _extra_cols = {
        "Measurement": ["value_as_number", "unit_source_value"],
        "Drug": ["quantity"],
    }

    events: list[dict] = []
    try:
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Person demographics
            cur.execute(
                f"""
                SELECT p.person_id, p.year_of_birth,
                       g.concept_name AS gender,
                       op.observation_period_start_date,
                       op.observation_period_end_date
                FROM {schema}.person p
                LEFT JOIN {schema}.concept g
                    ON g.concept_id = p.gender_concept_id
                LEFT JOIN {schema}.observation_period op
                    ON op.person_id = p.person_id
                WHERE p.person_id = %s
                LIMIT 1
                """,
                (person_id,),
            )
            person_row = cur.fetchone()
            if not person_row:
                raise HTTPException(status_code=404, detail="Person not found in CDM")
            person_info = dict(person_row)
            for k, v in person_info.items():
                if hasattr(v, "isoformat"):
                    person_info[k] = v.isoformat()

            # Query each clinical domain
            for domain_name, dcfg in DOMAIN_CONFIG.items():
                table = dcfg["table"]
                date_col = dcfg["date_col"]
                concept_col = dcfg["concept_id"]
                source_val = dcfg["source_value"]
                source_concept_col = dcfg.get("source_concept_id")
                end_date_col = _end_date.get(domain_name)
                extras = _extra_cols.get(domain_name, [])

                select_parts = [
                    f"t.{date_col} AS start_date",
                    f"t.{concept_col} AS concept_id",
                    f"t.{source_val} AS source_value",
                    "c.concept_name",
                ]
                if source_concept_col:
                    select_parts.append("sc.concept_name AS source_concept_name")
                if end_date_col:
                    select_parts.append(f"t.{end_date_col} AS end_date")
                for extra in extras:
                    select_parts.append(f"t.{extra}")

                join_clause = f"""
                    LEFT JOIN {schema}.concept c
                        ON c.concept_id = t.{concept_col}
                """
                if source_concept_col:
                    join_clause += f"""
                    LEFT JOIN {schema}.concept sc
                        ON sc.concept_id = t.{source_concept_col}
                    """

                sql = f"""
                    SELECT {', '.join(select_parts)}
                    FROM {schema}.{table} t
                    {join_clause}
                    WHERE t.person_id = %s
                    ORDER BY t.{date_col} NULLS LAST
                    LIMIT 500
                """
                try:
                    cur.execute(sql, (person_id,))
                    rows = cur.fetchall()
                except Exception:
                    logger.warning("Failed to fetch patient events for domain %s", domain_name, exc_info=True)
                    conn.rollback()
                    continue

                for row in rows:
                    evt: dict = {
                        "domain": domain_name,
                        "start_date": row["start_date"].isoformat() if hasattr(row.get("start_date"), "isoformat") else row.get("start_date"),
                        "concept_id": row.get("concept_id"),
                        "concept_name": row.get("concept_name") or "",
                        "source_value": row.get("source_value") or "",
                    }
                    if row.get("source_concept_name"):
                        evt["source_concept_name"] = row["source_concept_name"]
                    if end_date_col and row.get("end_date"):
                        evt["end_date"] = row["end_date"].isoformat() if hasattr(row["end_date"], "isoformat") else row["end_date"]
                    for extra in extras:
                        val = row.get(extra)
                        if val is not None:
                            evt[extra] = float(val) if isinstance(val, (int, float)) else str(val)
                    events.append(evt)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Patient journey query failed")
        raise HTTPException(status_code=500, detail="An internal error occurred during journey query")
    finally:
        conn.close()

    # Sort all events chronologically
    events.sort(key=lambda e: e.get("start_date") or "9999")

    return {"person": person_info, "events": events}


# ──── Cohort Version Diff ────

@router.get("/{cohort_id}/diff")
def diff_versions(
    cohort_id: int,
    version_a: int = Query(..., ge=1),
    version_b: int = Query(..., ge=1),
    db: Session = Depends(get_db),
):
    """
    Compare two versions of a cohort.
    Returns structural diff of criteria and patient count delta.
    """
    cohort = db.query(Cohort).filter(Cohort.id == cohort_id).first()
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")

    va = db.query(CohortVersion).filter(
        CohortVersion.cohort_id == cohort_id,
        CohortVersion.version == version_a,
    ).first()
    vb = db.query(CohortVersion).filter(
        CohortVersion.cohort_id == cohort_id,
        CohortVersion.version == version_b,
    ).first()

    if not va or not vb:
        raise HTTPException(status_code=404, detail="Version not found")

    criteria_a = va.criteria_json or {}
    criteria_b = vb.criteria_json or {}

    # Build structured diff
    diffs = _diff_criteria(criteria_a, criteria_b)

    count_a = va.patient_count
    count_b = vb.patient_count
    count_delta = None
    count_pct_change = None
    if count_a is not None and count_b is not None:
        count_delta = count_b - count_a
        if count_a > 0:
            count_pct_change = round((count_delta / count_a) * 100, 2)

    return {
        "cohort_id": cohort_id,
        "cohort_name": cohort.name,
        "version_a": version_a,
        "version_b": version_b,
        "patient_count_a": count_a,
        "patient_count_b": count_b,
        "patient_count_delta": count_delta,
        "patient_count_pct_change": count_pct_change,
        "criteria_a": criteria_a,
        "criteria_b": criteria_b,
        "diffs": diffs,
    }


def _diff_criteria(a: dict, b: dict) -> list[dict]:
    """Compute structural diff between two criteria JSON objects."""
    diffs = []

    # Compare inclusion criteria
    inc_a = a.get("inclusion", {}).get("criteria", [])
    inc_b = b.get("inclusion", {}).get("criteria", [])
    _diff_criterion_lists(inc_a, inc_b, "inclusion", diffs)

    # Compare exclusion criteria
    exc_a = a.get("exclusion", {}).get("criteria", [])
    exc_b = b.get("exclusion", {}).get("criteria", [])
    _diff_criterion_lists(exc_a, exc_b, "exclusion", diffs)

    # Compare demographics
    demo_a = a.get("demographics", {})
    demo_b = b.get("demographics", {})
    if demo_a != demo_b:
        diffs.append({
            "type": "modified",
            "section": "demographics",
            "detail": f"Demographics changed",
            "old": demo_a,
            "new": demo_b,
        })

    # Compare sameVisit
    sv_a = a.get("inclusion", {}).get("sameVisit", False)
    sv_b = b.get("inclusion", {}).get("sameVisit", False)
    if sv_a != sv_b:
        diffs.append({
            "type": "modified",
            "section": "inclusion",
            "detail": f"sameVisit changed: {sv_a} → {sv_b}",
            "old": sv_a,
            "new": sv_b,
        })

    return diffs


def _diff_criterion_lists(list_a: list, list_b: list, section: str, diffs: list):
    """Compare two lists of criteria, matching by 'id' field."""
    ids_a = {c.get("id"): c for c in list_a}
    ids_b = {c.get("id"): c for c in list_b}

    all_ids = set(ids_a.keys()) | set(ids_b.keys())
    for cid in all_ids:
        ca = ids_a.get(cid)
        cb = ids_b.get(cid)

        if ca and not cb:
            concepts = [c.get("concept_name", "") for c in ca.get("concepts", [])]
            diffs.append({
                "type": "removed",
                "section": section,
                "criterion_id": cid,
                "detail": f"Removed: {ca.get('domain', '?')} criterion ({', '.join(concepts[:3])})",
            })
        elif cb and not ca:
            concepts = [c.get("concept_name", "") for c in cb.get("concepts", [])]
            diffs.append({
                "type": "added",
                "section": section,
                "criterion_id": cid,
                "detail": f"Added: {cb.get('domain', '?')} criterion ({', '.join(concepts[:3])})",
            })
        elif ca != cb:
            changes = []
            if ca.get("concepts") != cb.get("concepts"):
                changes.append("concepts changed")
            if ca.get("occurrence") != cb.get("occurrence"):
                changes.append("occurrence changed")
            if ca.get("temporal") != cb.get("temporal"):
                changes.append("temporal changed")
            if ca.get("include_descendants") != cb.get("include_descendants"):
                changes.append("descendants changed")
            if ca.get("value") != cb.get("value"):
                changes.append("value constraint changed")
            diffs.append({
                "type": "modified",
                "section": section,
                "criterion_id": cid,
                "detail": f"Modified: {cb.get('domain', '?')} criterion — {', '.join(changes)}",
                "old": ca,
                "new": cb,
            })
