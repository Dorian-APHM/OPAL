"""
Concept Sets — Reusable groups of concepts.
CRUD + resolution (expand descendants) + counts.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from utils.cdm_helper import check_cdm_access
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from psycopg2 import sql as psysql

from db.app_db import get_db
from db.models import ConceptSet, CdmConfig, AnalysisSettings
from db.omop_connector import get_omop_connection
from utils.crypto import decrypt_password
from utils.sql_safety import safe_identifier
from config import DEFAULT_OMOP_SCHEMA, DOMAIN_CONFIG

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/concept-sets", tags=["concept-sets"])


def _get_cdm_conn(db: Session, cdm_name: str):
    cdm = db.query(CdmConfig).filter(CdmConfig.name == cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{cdm_name}' not found")
    password = decrypt_password(cdm.db_password_encrypted)
    conn = get_omop_connection(cdm.db_host, cdm.db_port, cdm.db_name, cdm.db_user, password)
    settings = db.query(AnalysisSettings).filter(AnalysisSettings.cdm_name == cdm_name).first()
    schema = safe_identifier(settings.omop_schema if settings else cdm.omop_schema or DEFAULT_OMOP_SCHEMA)
    return conn, schema


class ConceptSetCreate(BaseModel):
    name: str
    cdm_name: str
    domain: str | None = None
    description: str = ""
    concepts: list[dict] = []
    source_codes: list[dict] = []


class ConceptSetUpdate(BaseModel):
    name: str | None = None
    domain: str | None = None
    description: str | None = None
    concepts: list[dict] | None = None


def _parse_payload(concepts_json: str | None):
    """Parse concepts_json supporting old (list) and new (dict) formats."""
    if not concepts_json:
        return [], []
    data = json.loads(concepts_json)
    if isinstance(data, list):
        return data, []
    return data.get("concepts", []), data.get("source_codes", [])


def _count_items(concepts_json: str | None) -> int:
    concepts, source_codes = _parse_payload(concepts_json)
    return len(concepts) + len(source_codes)


@router.get("/")
def list_concept_sets(
    request: Request,
    cdm_name: str | None = None,
    domain: str | None = None,
    db=Depends(get_db),
):
    q = db.query(ConceptSet)
    if cdm_name:
        q = q.filter(ConceptSet.cdm_name == cdm_name)
    if domain:
        q = q.filter(ConceptSet.domain == domain)
    sets = q.order_by(ConceptSet.updated_at.desc()).all()
    return {
        "concept_sets": [
            {
                "id": s.id,
                "name": s.name,
                "cdm_name": s.cdm_name,
                "domain": s.domain,
                "description": s.description,
                "concept_count": _count_items(s.concepts_json),
                "created_by": s.created_by,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in sets
        ]
    }


@router.post("/")
def create_concept_set(body: ConceptSetCreate, request: Request, db=Depends(get_db)):
    check_cdm_access(request, body.cdm_name)
    user_info = getattr(request.state, "user", {})
    payload = {
        "concepts": body.concepts,
        "source_codes": body.source_codes,
    }
    cs = ConceptSet(
        name=body.name,
        cdm_name=body.cdm_name,
        domain=body.domain,
        description=body.description,
        concepts_json=json.dumps(payload),
        created_by=user_info.get("preferred_username", "system"),
    )
    db.add(cs)
    db.commit()
    db.refresh(cs)
    return {"id": cs.id, "name": cs.name}


@router.get("/{concept_set_id}")
def get_concept_set(concept_set_id: int, db=Depends(get_db)):
    cs = db.query(ConceptSet).filter(ConceptSet.id == concept_set_id).first()
    if not cs:
        return JSONResponse(status_code=404, content={"detail": "Concept set not found"})
    concepts, source_codes = _parse_payload(cs.concepts_json)
    return {
        "id": cs.id,
        "name": cs.name,
        "cdm_name": cs.cdm_name,
        "domain": cs.domain,
        "description": cs.description,
        "concepts": concepts,
        "source_codes": source_codes,
        "created_by": cs.created_by,
        "created_at": cs.created_at.isoformat() if cs.created_at else None,
        "updated_at": cs.updated_at.isoformat() if cs.updated_at else None,
    }


@router.put("/{concept_set_id}")
def update_concept_set(concept_set_id: int, body: ConceptSetUpdate, request: Request, db=Depends(get_db)):
    cs = db.query(ConceptSet).filter(ConceptSet.id == concept_set_id).first()
    if not cs:
        return JSONResponse(status_code=404, content={"detail": "Concept set not found"})
    user_info = getattr(request.state, "user", {})
    current_user = user_info.get("preferred_username", "system")
    is_admin = "admin" in user_info.get("roles", [])
    if cs.created_by != current_user and not is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    if body.name is not None:
        cs.name = body.name
    if body.domain is not None:
        cs.domain = body.domain
    if body.description is not None:
        cs.description = body.description
    if body.concepts is not None:
        cs.concepts_json = json.dumps(body.concepts)
    db.commit()
    return {"status": "ok", "id": cs.id}


@router.delete("/{concept_set_id}")
def delete_concept_set(concept_set_id: int, request: Request, db=Depends(get_db)):
    cs = db.query(ConceptSet).filter(ConceptSet.id == concept_set_id).first()
    if not cs:
        return JSONResponse(status_code=404, content={"detail": "Concept set not found"})
    user_info = getattr(request.state, "user", {})
    current_user = user_info.get("preferred_username", "system")
    is_admin = "admin" in user_info.get("roles", [])
    if cs.created_by != current_user and not is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    db.delete(cs)
    db.commit()
    return {"status": "ok"}


@router.get("/{concept_set_id}/resolve")
def resolve_concept_set(concept_set_id: int, request: Request, cdm_name: str | None = None, db=Depends(get_db)):
    """Resolve a concept set: return all concept_ids including descendants."""
    cs = db.query(ConceptSet).filter(ConceptSet.id == concept_set_id).first()
    if not cs:
        return JSONResponse(status_code=404, content={"detail": "Concept set not found"})

    concepts = json.loads(cs.concepts_json) if cs.concepts_json else []
    if not concepts:
        return {"concept_ids": [], "total": 0}

    target_cdm = cdm_name or cs.cdm_name
    check_cdm_access(request, target_cdm)
    conn, omop_schema = _get_cdm_conn(db, target_cdm)
    try:
        all_ids = set()
        expand_ids = []

        for c in concepts:
            cid = int(c["concept_id"])
            all_ids.add(cid)
            if c.get("include_descendants", True):
                expand_ids.append(cid)

        if expand_ids:
            cur = conn.cursor()
            sql = psysql.SQL(
                "SELECT DISTINCT descendant_concept_id FROM {}.{} "
                "WHERE ancestor_concept_id = ANY(%s)"
            ).format(psysql.Identifier(omop_schema), psysql.Identifier('concept_ancestor'))
            cur.execute(sql, (list(expand_ids),))
            for row in cur.fetchall():
                all_ids.add(row[0])
            cur.close()

        return {"concept_ids": sorted(all_ids), "total": len(all_ids)}
    finally:
        conn.close()


@router.post("/{concept_set_id}/counts")
def concept_set_counts(concept_set_id: int, body: dict, request: Request, db=Depends(get_db)):
    """Get record and person counts for each concept in the set."""
    cs = db.query(ConceptSet).filter(ConceptSet.id == concept_set_id).first()
    if not cs:
        return JSONResponse(status_code=404, content={"detail": "Concept set not found"})

    target_cdm = body.get("cdm_name", cs.cdm_name)
    check_cdm_access(request, target_cdm)
    concepts = json.loads(cs.concepts_json) if cs.concepts_json else []
    if not concepts:
        return {"counts": {}}

    concept_ids = [int(c["concept_id"]) for c in concepts]
    conn, omop_schema = _get_cdm_conn(db, target_cdm)
    try:
        counts = {}
        cur = conn.cursor()
        for cfg in DOMAIN_CONFIG.values():
            table = safe_identifier(cfg["table"])
            concept_col = safe_identifier(cfg["concept_id"])
            pid_col = safe_identifier(cfg["person_id"])
            try:
                sql = psysql.SQL(
                    "SELECT {concept_col}, COUNT(*) AS n_records, COUNT(DISTINCT {pid_col}) AS n_persons "
                    "FROM {schema}.{table} "
                    "WHERE {concept_col2} = ANY(%s) "
                    "GROUP BY {concept_col3}"
                ).format(
                    concept_col=psysql.Identifier(concept_col),
                    pid_col=psysql.Identifier(pid_col),
                    schema=psysql.Identifier(omop_schema),
                    table=psysql.Identifier(table),
                    concept_col2=psysql.Identifier(concept_col),
                    concept_col3=psysql.Identifier(concept_col),
                )
                cur.execute(sql, (concept_ids,))
                for row in cur.fetchall():
                    cid = row[0]
                    if cid not in counts:
                        counts[cid] = {"n_records": 0, "n_persons": 0}
                    counts[cid]["n_records"] += row[1]
                    counts[cid]["n_persons"] += row[2]
            except Exception:
                logger.warning("Failed to fetch concept set counts for domain", exc_info=True)
                conn.rollback()
                continue
        cur.close()
        return {"counts": counts}
    finally:
        conn.close()
