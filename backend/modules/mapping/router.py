"""
Mapping module API endpoints.

Provides mapping dashboard, unmapped exploration, auto-suggestion,
validation workflow, apply mapping, and audit history.
"""
import csv
import io
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from db.app_db import get_db
from db.models import CdmConfig, AnalysisSettings, AnalysisSnapshot, MappingDecision, ReferenceCodebook, SapbertMapping
from utils.notifications import notify
from db.omop_connector import get_omop_connection
from utils.crypto import decrypt_password
from config import DEFAULT_OMOP_SCHEMA, DOMAIN_CONFIG
from modules.mapping.suggest import suggest_mappings, suggest_batch
from utils.csv_safety import csv_safe
from utils.sql_safety import safe_identifier
from utils.rate_limit import limiter
from utils.cdm_helper import check_cdm_access, get_domain_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mapping", tags=["mapping"])

# Background suggestion tasks — survive page navigation
_active_suggestions: dict[str, dict] = {}
_suggestions_lock = __import__('threading').Lock()
# Stores: { task_id: { status, cdm_name, domain, results, error, cancelled, created_at } }
_SUGGESTION_TTL_SECONDS = 600  # 10 minutes — auto-evict completed/orphaned tasks


def _cleanup_stale_suggestions():
    """Remove suggestions older than TTL (completed or stuck)."""
    import time
    now = time.time()
    stale = [
        tid for tid, entry in _active_suggestions.items()
        if now - entry.get("created_at", 0) > _SUGGESTION_TTL_SECONDS
    ]
    for tid in stale:
        _active_suggestions.pop(tid, None)
    if stale:
        logger.info("Cleaned up %d stale suggestion tasks", len(stale))


# ──── Request models ────

class SuggestRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1, max_length=255)
    domain: str = Field(..., min_length=1, max_length=100)
    source_value: str = Field(..., min_length=1, max_length=1000)
    source_name: str = Field(default="", max_length=1000)


class SuggestBatchRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1, max_length=255)
    domain: str = Field(..., min_length=1, max_length=100)
    limit: int = Field(default=20, ge=1, le=200)
    enable_fuzzy: bool = True
    enable_keyword: bool = True
    enable_contextual: bool = True
    enable_sapbert: bool = True


class DecisionRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1, max_length=255)
    domain: str = Field(..., min_length=1, max_length=100)
    source_value: str = Field(..., min_length=1, max_length=1000)
    source_name: str = Field(default="", max_length=1000)
    action: str = Field(..., pattern=r"^(approved|modified|rejected)$")
    target_concept_id: int | None = None
    target_concept_name: str = Field(default="", max_length=500)
    target_vocabulary_id: str = Field(default="", max_length=100)
    suggestion_source: str = Field(default="", max_length=50)
    confidence_score: float | None = Field(default=None, ge=0.0, le=100.0)
    reason: str = Field(default="", max_length=5000)


class BulkDecisionRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1, max_length=255)
    domain: str = Field(..., min_length=1, max_length=100)
    action: str = Field(..., pattern=r"^(approved|rejected)$")
    min_confidence: float = Field(default=80.0, ge=0.0, le=100.0)
    source_values: list[str] | None = Field(default=None, max_length=1000)


class ApplyMappingRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1, max_length=255)
    domain: str = Field(..., min_length=1, max_length=100)
    write_to_cdm: bool = False


# ──── Helpers ────

def _get_cdm_conn(db: Session, cdm_name: str):
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


def _get_schema(db: Session, cdm: CdmConfig) -> str:
    settings = db.query(AnalysisSettings).filter(
        AnalysisSettings.cdm_name == cdm.name
    ).first()
    raw = settings.omop_schema if settings else cdm.omop_schema or DEFAULT_OMOP_SCHEMA
    return safe_identifier(raw)


# ──── 5.1 Mapping Dashboard ────

@router.get("/dashboard/{cdm_name}")
def mapping_dashboard(cdm_name: str, db: Session = Depends(get_db)):
    """
    Mapping rates by domain with record counts.
    Uses latest quality analysis snapshots per domain.
    """
    # P44 fix: single query with DISTINCT ON instead of N+1 loop
    from sqlalchemy import text
    latest_snapshots = (
        db.query(AnalysisSnapshot)
        .filter(
            AnalysisSnapshot.cdm_name == cdm_name,
            AnalysisSnapshot.domain.in_(list(DOMAIN_CONFIG.keys())),
        )
        .order_by(AnalysisSnapshot.domain, AnalysisSnapshot.version.desc())
        .distinct(AnalysisSnapshot.domain)
        .all()
    )
    domains_data = []
    for snapshot in latest_snapshots:
        results = snapshot.results
        mapping = results.get("mapping", {})
        terms = mapping.get("terms", {})
        rows = mapping.get("rows", {})
        domains_data.append({
            "domain": snapshot.domain,
            "total_terms": terms.get("total_terms", 0),
            "mapped_terms": terms.get("mapped_terms", 0),
            "unmapped_terms": terms.get("unmapped_terms", 0),
            "pct_terms_mapped": terms.get("pct_terms_mapped", 0),
            "total_rows": rows.get("total_rows", 0),
            "mapped_rows": rows.get("mapped_rows", 0),
            "unmapped_rows": rows.get("unmapped_rows", 0),
            "pct_rows_mapped": rows.get("pct_rows_mapped", 0),
            "version": snapshot.version,
            "snapshot_date": snapshot.created_at.isoformat() if snapshot.created_at else None,
        })

    # Decisions summary
    decision_counts = (
        db.query(
            MappingDecision.action,
            func.count(MappingDecision.id).label("count"),
        )
        .filter(MappingDecision.cdm_name == cdm_name)
        .group_by(MappingDecision.action)
        .all()
    )
    decisions_summary = {r.action: r.count for r in decision_counts}

    return {
        "cdm_name": cdm_name,
        "domains": domains_data,
        "decisions_summary": decisions_summary,
    }


@router.get("/dashboard/{cdm_name}/evolution")
def mapping_evolution(cdm_name: str, domain: str, db: Session = Depends(get_db)):
    """Mapping rate evolution across snapshot versions for a domain."""
    snapshots = (
        db.query(AnalysisSnapshot)
        .filter(AnalysisSnapshot.cdm_name == cdm_name, AnalysisSnapshot.domain == domain)
        .order_by(AnalysisSnapshot.version.asc())
        .all()
    )
    evolution = []
    for s in snapshots:
        terms = s.results.get("mapping", {}).get("terms", {})
        evolution.append({
            "version": s.version,
            "date": s.created_at.isoformat() if s.created_at else None,
            "pct_terms_mapped": terms.get("pct_terms_mapped", 0),
            "pct_rows_mapped": s.results.get("mapping", {}).get("rows", {}).get("pct_rows_mapped", 0),
            "total_terms": terms.get("total_terms", 0),
            "unmapped_terms": terms.get("unmapped_terms", 0),
        })
    return {"cdm_name": cdm_name, "domain": domain, "evolution": evolution}


# ──── 5.1b Strategy Confidence Statistics ────

@router.get("/strategies/{cdm_name}")
def strategy_stats(
    cdm_name: str,
    domain: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Compute confidence statistics per suggestion strategy.
    Returns per-strategy: total decisions, approval rate, avg confidence,
    rejection rate, and modification rate.
    """
    # P45 fix: push aggregation to SQL instead of loading all decisions into memory
    from sqlalchemy import case, literal_column
    query = db.query(
        MappingDecision.suggestion_source,
        func.count(MappingDecision.id).label("total"),
        func.count(case((MappingDecision.action == "approved", 1))).label("approved"),
        func.count(case((MappingDecision.action == "modified", 1))).label("modified"),
        func.count(case((MappingDecision.action == "rejected", 1))).label("rejected"),
        func.avg(MappingDecision.confidence_score).label("avg_confidence"),
        func.avg(case((MappingDecision.action == "approved", MappingDecision.confidence_score))).label("avg_confidence_approved"),
        func.avg(case((MappingDecision.action == "rejected", MappingDecision.confidence_score))).label("avg_confidence_rejected"),
    ).filter(
        MappingDecision.cdm_name == cdm_name,
        MappingDecision.suggestion_source.isnot(None),
        MappingDecision.suggestion_source != "",
        MappingDecision.suggestion_source != "bulk",
        ~MappingDecision.suggestion_source.startswith("rollback"),
    ).group_by(MappingDecision.suggestion_source)

    if domain:
        query = query.filter(MappingDecision.domain == domain)

    rows = query.all()

    strategies = []
    for r in rows:
        total = r.total
        approved = r.approved
        modified = r.modified
        rejected = r.rejected
        strategies.append({
            "strategy": r.suggestion_source,
            "total_decisions": total,
            "approved": approved,
            "modified": modified,
            "rejected": rejected,
            "approval_rate": round(approved / total * 100, 1) if total > 0 else 0,
            "rejection_rate": round(rejected / total * 100, 1) if total > 0 else 0,
            "modification_rate": round(modified / total * 100, 1) if total > 0 else 0,
            "avg_confidence": round(float(r.avg_confidence), 1) if r.avg_confidence is not None else None,
            "avg_confidence_approved": round(float(r.avg_confidence_approved), 1) if r.avg_confidence_approved is not None else None,
            "avg_confidence_rejected": round(float(r.avg_confidence_rejected), 1) if r.avg_confidence_rejected is not None else None,
        })

    # Sort by approval rate descending
    strategies.sort(key=lambda s: s["approval_rate"], reverse=True)

    return {
        "cdm_name": cdm_name,
        "domain": domain,
        "strategies": strategies,
        "total_decisions": sum(s["total_decisions"] for s in strategies),
    }


# ──── 5.2 Unmapped Exploration ────

@router.get("/unmapped/{cdm_name}/{domain}")
def list_unmapped(
    cdm_name: str,
    domain: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    search: str = Query(default=""),
    include_mapped: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """
    Paginated list of unmapped source values for a domain,
    queried directly from the CDM.
    If include_mapped=True, also returns already-mapped codes (for manual mapping).
    """
    if domain not in DOMAIN_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown domain: {domain}")

    cdm, conn = _get_cdm_conn(db, cdm_name)
    schema = _get_schema(db, cdm)
    cfg = get_domain_config(conn, schema, domain)
    table = safe_identifier(cfg["table"])
    sv_col = safe_identifier(cfg["source_value"])
    concept_col = safe_identifier(cfg["concept_id"])
    sn_col = safe_identifier(cfg["source_name"]) if cfg.get("source_name") else None
    full_table = f"{schema}.{table}"

    try:
        from psycopg2.extras import DictCursor
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # Build query
            select_cols = [f"t.{sv_col} AS source_value"]
            if sn_col:
                select_cols.append(f"MAX(t.{sn_col}) AS source_name")
            else:
                select_cols.append("'' AS source_name")

            wheres: list[str] = []
            if not include_mapped:
                wheres.append(f"(t.{concept_col} = 0 OR t.{concept_col} IS NULL)")
            params: dict = {}

            if search:
                search_clause = f"t.{sv_col} ILIKE %(search)s"
                if sn_col:
                    search_clause = f"({search_clause} OR t.{sn_col} ILIKE %(search)s)"
                wheres.append(search_clause)
                params["search"] = f"%{search}%"

            where_clause = " AND ".join(wheres)
            offset = (page - 1) * page_size
            params["lim"] = page_size
            params["off"] = offset

            # Count total
            count_sql = f"""
                SELECT COUNT(DISTINCT t.{sv_col}) AS total
                FROM {full_table} t
                WHERE {where_clause}
            """
            cur.execute(count_sql, params)
            total = cur.fetchone()["total"]

            # Get page
            data_sql = f"""
                SELECT {', '.join(select_cols)},
                       COUNT(*) AS n_records,
                       COUNT(DISTINCT t.person_id) AS n_persons
                FROM {full_table} t
                WHERE {where_clause}
                GROUP BY t.{sv_col}
                ORDER BY COUNT(*) DESC
                LIMIT %(lim)s OFFSET %(off)s
            """
            cur.execute(data_sql, params)
            rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.exception("Unmapped listing failed")
        raise HTTPException(status_code=500, detail="An internal error occurred while listing unmapped terms")
    finally:
        conn.close()

    return {
        "domain": domain,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        "items": rows,
    }


@router.get("/unmapped/{cdm_name}/{domain}/export")
def export_unmapped(
    cdm_name: str, domain: str,
    search: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Export all unmapped terms for a domain as CSV."""
    if domain not in DOMAIN_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown domain: {domain}")

    cdm, conn = _get_cdm_conn(db, cdm_name)
    schema = _get_schema(db, cdm)
    cfg = get_domain_config(conn, schema, domain)
    table = safe_identifier(cfg["table"])
    sv_col = safe_identifier(cfg["source_value"])
    concept_col = safe_identifier(cfg["concept_id"])
    sn_col = safe_identifier(cfg["source_name"]) if cfg.get("source_name") else None
    full_table = f"{schema}.{table}"

    try:
        from psycopg2.extras import DictCursor
        with conn.cursor(cursor_factory=DictCursor) as cur:
            select_cols = [f"t.{sv_col} AS source_value"]
            if sn_col:
                select_cols.append(f"MAX(t.{sn_col}) AS source_name")

            wheres = [f"(t.{concept_col} = 0 OR t.{concept_col} IS NULL)"]
            params: dict = {}
            if search:
                wheres.append(f"t.{sv_col} ILIKE %(search)s")
                params["search"] = f"%{search}%"

            sql = f"""
                SELECT {', '.join(select_cols)},
                       COUNT(*) AS n_records,
                       COUNT(DISTINCT t.person_id) AS n_persons
                FROM {full_table} t
                WHERE {" AND ".join(wheres)}
                GROUP BY t.{sv_col}
                ORDER BY COUNT(*) DESC
            """
            cur.execute(sql, params)
            rows = cur.fetchall()
    except Exception as e:
        logger.exception("Export of unmapped terms failed")
        raise HTTPException(status_code=500, detail="An internal error occurred during export")
    finally:
        conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    header = ["source_value"]
    if sn_col:
        header.append("source_name")
    header.extend(["n_records", "n_persons"])
    writer.writerow(header)
    for r in rows:
        row = [csv_safe(r["source_value"])]
        if sn_col:
            row.append(csv_safe(r.get("source_name", "")))
        row.extend([r["n_records"], r["n_persons"]])
        writer.writerow(row)
    output.seek(0)

    filename = f"unmapped_{cdm_name}_{domain}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ──── 5.2b Concept Lookup (for manual mapping) ────

@router.get("/concept-lookup/{cdm_name}/{concept_id}")
def concept_lookup(cdm_name: str, concept_id: int, db: Session = Depends(get_db)):
    """
    Look up a single concept by ID from the CDM vocabulary.
    Used by the manual mapping workflow to validate a concept_id.
    """
    cdm, conn = _get_cdm_conn(db, cdm_name)
    schema = _get_schema(db, cdm)

    try:
        from psycopg2.extras import DictCursor
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(f"""
                SELECT concept_id, concept_name, concept_code,
                       vocabulary_id, domain_id, standard_concept, concept_class_id
                FROM {schema}.concept
                WHERE concept_id = %(cid)s
            """, {"cid": concept_id})
            row = cur.fetchone()
    except Exception as e:
        logger.exception("Concept lookup failed")
        raise HTTPException(status_code=500, detail="An internal error occurred during concept lookup")
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Concept {concept_id} not found")

    return {
        "concept_id": row["concept_id"],
        "concept_name": row["concept_name"],
        "concept_code": row["concept_code"],
        "vocabulary_id": row["vocabulary_id"],
        "domain_id": row["domain_id"],
        "standard_concept": row["standard_concept"],
        "concept_class_id": row["concept_class_id"],
    }


# ──── 5.3 Auto-Suggestion ────

def _get_sapbert_suggestions(db: Session, source_value: str, domain: str) -> list[dict]:
    """Look up pre-computed SapBERT suggestions for a source value."""
    rows = (
        db.query(SapbertMapping)
        .filter(
            SapbertMapping.domain == domain,
            SapbertMapping.source_code == source_value,
        )
        .order_by(SapbertMapping.rank)
        .all()
    )
    return [
        {
            "concept_id": r.target_concept_id,
            "concept_name": r.target_concept_name,
            "concept_code": r.target_concept_code,
            "vocabulary_id": r.target_vocabulary_id,
            "domain_id": domain,
            "standard_concept": "S",
            "confidence": int(r.similarity * 100),
            "source": "sapbert",
        }
        for r in rows
    ]


@router.post("/suggest")
def suggest_single(req: SuggestRequest, request: Request, db: Session = Depends(get_db)):
    """Get mapping suggestions for a single source term."""
    # cdm_name is in the JSON body, so the Keycloak middleware cannot see it — check here.
    check_cdm_access(request, req.cdm_name)
    source_name = req.source_name or ""

    # Enrich from reference codebook if no source_name
    if not source_name:
        ref = db.query(ReferenceCodebook.description).filter(
            ReferenceCodebook.domain == req.domain,
            ReferenceCodebook.code == req.source_value,
        ).first()
        if ref:
            source_name = ref.description

    # Check SapBERT pre-computed suggestions first
    sapbert_suggs = _get_sapbert_suggestions(db, req.source_value, req.domain)

    cdm, conn = _get_cdm_conn(db, req.cdm_name)
    schema = _get_schema(db, cdm)
    try:
        suggestions = suggest_mappings(
            conn, req.source_value, source_name or None,
            req.domain, schema,
        )
    except Exception as e:
        logger.exception("Suggestion failed")
        raise HTTPException(status_code=500, detail="An internal error occurred during suggestion")
    finally:
        conn.close()

    # Merge: SapBERT first, then other strategies (deduplicated)
    if sapbert_suggs:
        seen_ids = {s["concept_id"] for s in sapbert_suggs}
        merged = list(sapbert_suggs)
        for s in suggestions:
            if s["concept_id"] not in seen_ids:
                merged.append(s)
                seen_ids.add(s["concept_id"])
        suggestions = merged

    return {"source_value": req.source_value, "suggestions": suggestions}


@router.post("/suggest/batch")
@limiter.limit("3/minute")
def suggest_batch_endpoint(req: SuggestBatchRequest, request: Request, db: Session = Depends(get_db)):
    """
    Launch mapping suggestions in a background thread.
    Returns immediately with a task_id. Poll /suggest/status/{task_id} for results.
    """
    # cdm_name is in the JSON body, so the Keycloak middleware cannot see it — check here.
    check_cdm_access(request, req.cdm_name)
    import threading
    import uuid as _uuid

    if req.domain not in DOMAIN_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown domain: {req.domain}")

    # Gather all data needed by the worker while we still have the DB session
    cdm, conn = _get_cdm_conn(db, req.cdm_name)
    schema = _get_schema(db, cdm)
    cfg = get_domain_config(conn, schema, req.domain)
    approved_svs = [
        r[0] for r in
        db.query(MappingDecision.source_value)
        .filter(
            MappingDecision.cdm_name == req.cdm_name,
            MappingDecision.domain == req.domain,
            MappingDecision.action.in_(["approved", "modified", "rejected"]),
        ).all()
    ]

    # SapBERT mappings are now fetched lazily in the worker after we know
    # which terms to process (P46 fix: avoid loading 100K+ rows upfront).
    sapbert_domain = req.domain

    # Pre-fetch reference codebooks
    ref_rows = db.query(ReferenceCodebook.code, ReferenceCodebook.description).filter(
        ReferenceCodebook.domain == req.domain
    ).all()
    ref_map = {r.code: r.description for r in ref_rows}

    import time as _time
    task_id = str(_uuid.uuid4())[:8]
    with _suggestions_lock:
        _cleanup_stale_suggestions()
        _active_suggestions[task_id] = {
            "status": "running", "cdm_name": req.cdm_name, "domain": req.domain,
            "results": None, "error": None, "cancelled": False,
            "created_at": _time.time(),
        }

    # Capture request params for worker
    domain = req.domain
    limit = req.limit
    enable_fuzzy = req.enable_fuzzy
    enable_keyword = req.enable_keyword
    enable_contextual = req.enable_contextual
    enable_sapbert = req.enable_sapbert

    def _worker():
        try:
            from psycopg2.extras import DictCursor
            _table = safe_identifier(cfg["table"])
            full_table = f"{schema}.{_table}"
            sv_col = safe_identifier(cfg["source_value"])
            concept_col = safe_identifier(cfg["concept_id"])
            sn_col = safe_identifier(cfg["source_name"]) if cfg.get("source_name") else None

            with conn.cursor(cursor_factory=DictCursor) as cur:
                select_cols = [f"t.{sv_col} AS source_value"]
                if sn_col:
                    select_cols.append(f"MAX(t.{sn_col}) AS source_name")
                else:
                    select_cols.append("'' AS source_name")

                where_clauses = [f"(t.{concept_col} = 0 OR t.{concept_col} IS NULL)"]
                params: dict = {"lim": limit}
                if approved_svs:
                    where_clauses.append(f"t.{sv_col} != ALL(%(approved)s)")
                    params["approved"] = approved_svs

                sql = f"""
                    SELECT {', '.join(select_cols)}, COUNT(*) AS n_records
                    FROM {full_table} t
                    WHERE {' AND '.join(where_clauses)}
                    GROUP BY t.{sv_col}
                    ORDER BY COUNT(*) DESC
                    LIMIT %(lim)s
                """
                cur.execute(sql, params)
                terms = [dict(r) for r in cur.fetchall()]

            # Enrich with reference codebook
            for t in terms:
                if not t.get("source_name") and t["source_value"] in ref_map:
                    t["source_name"] = ref_map[t["source_value"]]

            with _suggestions_lock:
                if _active_suggestions.get(task_id, {}).get("cancelled"):
                    return

            # P46 fix: fetch SapBERT only for the terms we need (not all domain)
            all_svs = [t["source_value"] for t in terms]
            sapbert_map: dict[str, list[dict]] = {}
            if enable_sapbert and all_svs:
                from db.app_db import SessionLocal
                _db = SessionLocal()
                try:
                    sapbert_rows = (
                        _db.query(SapbertMapping)
                        .filter(
                            SapbertMapping.domain == sapbert_domain,
                            SapbertMapping.source_code.in_(all_svs),
                        )
                        .order_by(SapbertMapping.source_code, SapbertMapping.rank)
                        .all()
                    )
                    for r in sapbert_rows:
                        sapbert_map.setdefault(r.source_code, []).append({
                            "concept_id": r.target_concept_id,
                            "concept_name": r.target_concept_name,
                            "concept_code": r.target_concept_code,
                            "vocabulary_id": r.target_vocabulary_id,
                            "domain_id": sapbert_domain,
                            "standard_concept": "S",
                            "confidence": int(r.similarity * 100),
                            "source": "sapbert",
                        })
                finally:
                    _db.close()

            terms_without_sapbert = [t for t in terms if t["source_value"] not in sapbert_map]

            results_sapbert = []
            for t in terms:
                sv = t["source_value"]
                if sv in sapbert_map:
                    results_sapbert.append({
                        "source_value": sv,
                        "source_name": t.get("source_name", ""),
                        "suggestions": list(sapbert_map[sv]),
                    })

            with _suggestions_lock:
                if _active_suggestions.get(task_id, {}).get("cancelled"):
                    return

            results_slow = []
            if terms_without_sapbert:
                results_slow = suggest_batch(conn, terms_without_sapbert, domain, schema,
                                             enable_fuzzy=enable_fuzzy,
                                             enable_keyword=enable_keyword,
                                             enable_contextual=enable_contextual)

            result_map = {}
            for r in results_sapbert + results_slow:
                result_map[r["source_value"]] = r
            results = [result_map[t["source_value"]] for t in terms if t["source_value"] in result_map]

            with _suggestions_lock:
                if task_id in _active_suggestions:
                    _active_suggestions[task_id]["status"] = "done"
                    _active_suggestions[task_id]["results"] = results

        except Exception as e:
            logger.exception("Background batch suggestion failed")
            with _suggestions_lock:
                if task_id in _active_suggestions:
                    _active_suggestions[task_id]["status"] = "error"
                    _active_suggestions[task_id]["error"] = "An internal error occurred during batch suggestion"
        finally:
            try:
                conn.close()
            except Exception:
                pass

    from utils.thread_pool import submit_task
    submit_task(_worker)
    return {"task_id": task_id, "status": "running"}


@router.get("/suggest/status/{task_id}")
def suggest_status(task_id: str):
    """Check status of a background suggestion task."""
    with _suggestions_lock:
        entry = _active_suggestions.get(task_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Task not found")
    resp: dict = {"task_id": task_id, "status": entry["status"], "domain": entry["domain"]}
    if entry["status"] == "done":
        resp["results"] = entry["results"]
        # Clean up after delivering results
        with _suggestions_lock:
            _active_suggestions.pop(task_id, None)
    elif entry["status"] == "error":
        resp["error"] = entry["error"]
        with _suggestions_lock:
            _active_suggestions.pop(task_id, None)
    return resp


@router.post("/suggest/cancel/{task_id}")
def suggest_cancel(task_id: str):
    """Cancel a running suggestion task."""
    with _suggestions_lock:
        entry = _active_suggestions.get(task_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Task not found")
        entry["cancelled"] = True
        _active_suggestions.pop(task_id, None)
    return {"cancelled": True, "task_id": task_id}


@router.get("/suggest/active")
def suggest_active():
    """List running suggestion tasks."""
    with _suggestions_lock:
        items = list(_active_suggestions.items())
    return {
        "active": [
            {"task_id": tid, "cdm_name": info["cdm_name"], "domain": info["domain"], "status": info["status"]}
            for tid, info in items
        ]
    }


# ──── 5.4 Validation Workflow ────

@router.post("/decide")
def record_decision(req: DecisionRequest, request: Request, db: Session = Depends(get_db)):
    """Record a mapping decision (approve, modify, reject)."""
    # cdm_name is in the JSON body, so the Keycloak middleware cannot see it — check here.
    check_cdm_access(request, req.cdm_name)
    if req.action not in ("approved", "modified", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid action")

    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "system")

    decision = MappingDecision(
        cdm_name=req.cdm_name,
        domain=req.domain,
        source_value=req.source_value,
        source_name=req.source_name,
        action=req.action,
        target_concept_id=req.target_concept_id,
        target_concept_name=req.target_concept_name,
        target_vocabulary_id=req.target_vocabulary_id,
        suggestion_source=req.suggestion_source,
        confidence_score=req.confidence_score,
        reason=req.reason,
    )
    db.add(decision)

    notify(
        db, username, "mapping_review",
        title=f"Décision mapping : {req.action}",
        message=f"{username} a {req.action} « {req.source_value} » dans {req.domain} ({req.cdm_name}).",
        link=f"/mapping?cdm={req.cdm_name}&domain={req.domain}",
        item_id=f"{req.cdm_name}:{req.domain}",
    )

    db.commit()
    db.refresh(decision)

    return {"id": decision.id, "action": decision.action}


@router.post("/decide/bulk")
def bulk_decision(req: BulkDecisionRequest, request: Request, db: Session = Depends(get_db)):
    """
    Bulk approve or reject suggestions above a confidence threshold.
    Either uses source_values list or processes all pending terms.
    """
    # cdm_name is in the JSON body, so the Keycloak middleware cannot see it — check here.
    check_cdm_access(request, req.cdm_name)
    if req.action not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid action for bulk")

    if req.source_values:
        # Get existing source values in one query, filtered to only the requested values
        existing = set(
            r[0] for r in
            db.query(MappingDecision.source_value)
            .filter(
                MappingDecision.cdm_name == req.cdm_name,
                MappingDecision.domain == req.domain,
                MappingDecision.source_value.in_(req.source_values),
            ).all()
        )
        new_values = [sv for sv in req.source_values if sv not in existing]
        if new_values:
            db.bulk_save_objects([
                MappingDecision(
                    cdm_name=req.cdm_name,
                    domain=req.domain,
                    source_value=sv,
                    action=req.action,
                    suggestion_source="bulk",
                )
                for sv in new_values
            ])
            db.commit()
        count = len(new_values)
    else:
        count = 0

    return {"action": req.action, "count": count}


# ──── 5.5 Apply Mapping ────

@router.post("/apply")
def apply_mapping(req: ApplyMappingRequest, request: Request, db: Session = Depends(get_db)):
    """
    Generate source_to_concept_map entries from approved decisions.
    Optionally writes directly to the CDM's source_to_concept_map table.
    """
    # cdm_name is in the JSON body, so the Keycloak middleware cannot see it — check here.
    check_cdm_access(request, req.cdm_name)
    # Get all approved/modified decisions
    decisions = (
        db.query(MappingDecision)
        .filter(
            MappingDecision.cdm_name == req.cdm_name,
            MappingDecision.domain == req.domain,
            MappingDecision.action.in_(["approved", "modified"]),
            MappingDecision.target_concept_id.isnot(None),
        )
        .all()
    )

    if not decisions:
        return {"message": "No approved mappings to apply", "count": 0}

    stcm_rows = []
    for d in decisions:
        stcm_rows.append({
            "source_code": d.source_value,
            "source_concept_id": 0,
            "source_vocabulary_id": f"OPAL_{req.domain}",
            "source_code_description": d.source_name or d.source_value,
            "target_concept_id": d.target_concept_id,
            "target_vocabulary_id": d.target_vocabulary_id or "SNOMED",
            "valid_start_date": "1970-01-01",
            "valid_end_date": "2099-12-31",
            "invalid_reason": None,
        })

    # ── CDM write disabled — CDM connections are strictly read-only ──
    # To re-enable, remove the guard below and uncomment the write block.
    if req.write_to_cdm:
        raise HTTPException(
            status_code=403,
            detail="L'écriture dans le CDM est désactivée. Utilisez l'export CSV pour appliquer le mapping manuellement.",
        )

    # --- Write block (disabled) ---
    # if req.write_to_cdm:
    #     cdm, conn = _get_cdm_conn(db, req.cdm_name)
    #     schema = _get_schema(db, cdm)
    #     try:
    #         from psycopg2.extras import execute_values
    #         with conn.cursor() as cur:
    #             sql = f"""
    #                 INSERT INTO {schema}.source_to_concept_map
    #                     (source_code, source_concept_id, source_vocabulary_id,
    #                      source_code_description, target_concept_id, target_vocabulary_id,
    #                      valid_start_date, valid_end_date, invalid_reason)
    #                 VALUES %s
    #                 ON CONFLICT (source_code, source_vocabulary_id, target_concept_id) DO UPDATE
    #                 SET source_code_description = EXCLUDED.source_code_description,
    #                     target_vocabulary_id = EXCLUDED.target_vocabulary_id
    #             """
    #             values = [
    #                 (row["source_code"], row["source_concept_id"], row["source_vocabulary_id"],
    #                  row["source_code_description"], row["target_concept_id"], row["target_vocabulary_id"],
    #                  row["valid_start_date"], row["valid_end_date"], row["invalid_reason"])
    #                 for row in stcm_rows
    #             ]
    #             execute_values(cur, sql, values)
    #             conn.commit()
    #     except Exception as e:
    #         conn.rollback()
    #         raise HTTPException(status_code=500, detail=f"Write error: {e}")
    #     finally:
    #         conn.close()
    # --- End write block ---

    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "system")
    notify(
        db, username, "mapping_applied",
        title=f"Mapping exporté : {req.domain}",
        message=f"{len(stcm_rows)} mappings générés pour {req.domain} ({req.cdm_name}).",
        link=f"/mapping?cdm={req.cdm_name}&domain={req.domain}",
        target_role="data-manager",
        item_id=f"{req.cdm_name}:{req.domain}",
    )
    db.commit()

    return {
        "count": len(stcm_rows),
        "written_to_cdm": False,
        "rows": stcm_rows,
    }


@router.post("/apply/preview")
def apply_preview(req: ApplyMappingRequest, request: Request, db: Session = Depends(get_db)):
    """Preview impact of applying approved mappings."""
    # cdm_name is in the JSON body, so the Keycloak middleware cannot see it — check here.
    check_cdm_access(request, req.cdm_name)
    decisions = (
        db.query(MappingDecision)
        .filter(
            MappingDecision.cdm_name == req.cdm_name,
            MappingDecision.domain == req.domain,
            MappingDecision.action.in_(["approved", "modified"]),
            MappingDecision.target_concept_id.isnot(None),
        )
        .all()
    )

    if not decisions or req.domain not in DOMAIN_CONFIG:
        return {"total_decisions": 0, "impacted_rows": 0, "impacted_persons": 0}

    cdm, conn = _get_cdm_conn(db, req.cdm_name)
    schema = _get_schema(db, cdm)
    cfg = get_domain_config(conn, schema, req.domain)
    table = safe_identifier(cfg["table"])
    full_table = f"{schema}.{table}"
    sv_col = safe_identifier(cfg["source_value"])

    source_values = [d.source_value for d in decisions]

    try:
        from psycopg2.extras import DictCursor
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(f"""
                SELECT COUNT(*) AS n_rows, COUNT(DISTINCT person_id) AS n_persons
                FROM {full_table}
                WHERE {sv_col} = ANY(%(svs)s)
            """, {"svs": source_values})
            row = cur.fetchone()
    except Exception as e:
        logger.exception("Mapping preview query failed")
        raise HTTPException(status_code=500, detail="An internal error occurred during preview")
    finally:
        conn.close()

    return {
        "total_decisions": len(decisions),
        "impacted_rows": row["n_rows"] if row else 0,
        "impacted_persons": row["n_persons"] if row else 0,
    }


@router.get("/apply/export/{cdm_name}/{domain}")
def export_stcm(cdm_name: str, domain: str, db: Session = Depends(get_db)):
    """Export approved mappings as source_to_concept_map CSV."""
    decisions = (
        db.query(MappingDecision)
        .filter(
            MappingDecision.cdm_name == cdm_name,
            MappingDecision.domain == domain,
            MappingDecision.action.in_(["approved", "modified"]),
            MappingDecision.target_concept_id.isnot(None),
        )
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "source_code", "source_concept_id", "source_vocabulary_id",
        "source_code_description", "target_concept_id", "target_vocabulary_id",
        "valid_start_date", "valid_end_date", "invalid_reason",
    ])
    for d in decisions:
        writer.writerow([
            csv_safe(d.source_value), 0, f"OPAL_{domain}",
            csv_safe(d.source_name or d.source_value),
            d.target_concept_id, csv_safe(d.target_vocabulary_id or "SNOMED"),
            "1970-01-01", "2099-12-31", "",
        ])
    output.seek(0)

    filename = f"source_to_concept_map_{cdm_name}_{domain}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ──── 5.6 History & Audit ────

@router.get("/history/{cdm_name}")
def mapping_history(
    cdm_name: str,
    domain: str | None = None,
    action: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Paginated mapping decision history with filters."""
    query = db.query(MappingDecision).filter(MappingDecision.cdm_name == cdm_name)

    if domain:
        query = query.filter(MappingDecision.domain == domain)
    if action:
        query = query.filter(MappingDecision.action == action)

    total = query.count()
    offset = (page - 1) * page_size
    decisions = query.order_by(desc(MappingDecision.created_at)).offset(offset).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        "items": [
            {
                "id": d.id,
                "domain": d.domain,
                "source_value": d.source_value,
                "source_name": d.source_name,
                "action": d.action,
                "target_concept_id": d.target_concept_id,
                "target_concept_name": d.target_concept_name,
                "target_vocabulary_id": d.target_vocabulary_id,
                "previous_concept_id": d.previous_concept_id,
                "suggestion_source": d.suggestion_source,
                "confidence_score": d.confidence_score,
                "user": d.user,
                "reason": d.reason or "",
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in decisions
        ],
    }


@router.post("/history/{decision_id}/rollback")
def rollback_decision(decision_id: int, db: Session = Depends(get_db)):
    """Rollback a specific mapping decision."""
    decision = db.query(MappingDecision).filter(MappingDecision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    # Create a rollback entry
    rollback = MappingDecision(
        cdm_name=decision.cdm_name,
        domain=decision.domain,
        source_value=decision.source_value,
        source_name=decision.source_name,
        action="rolled_back",
        target_concept_id=None,
        previous_concept_id=decision.target_concept_id,
        suggestion_source=f"rollback of #{decision.id}",
    )
    db.add(rollback)

    # Remove the original decision
    db.delete(decision)
    db.commit()

    return {"rolled_back": True, "original_id": decision_id}


@router.get("/history/{cdm_name}/export")
def export_history(cdm_name: str, domain: str | None = None, db: Session = Depends(get_db)):
    """Export full mapping history as CSV."""
    query = db.query(MappingDecision).filter(MappingDecision.cdm_name == cdm_name)
    if domain:
        query = query.filter(MappingDecision.domain == domain)
    decisions = query.order_by(desc(MappingDecision.created_at)).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "domain", "source_value", "source_name", "action",
        "target_concept_id", "target_concept_name", "target_vocabulary_id",
        "previous_concept_id", "suggestion_source", "confidence_score",
        "user", "created_at",
    ])
    for d in decisions:
        writer.writerow([
            d.id, csv_safe(d.domain), csv_safe(d.source_value), csv_safe(d.source_name), csv_safe(d.action),
            d.target_concept_id, csv_safe(d.target_concept_name), csv_safe(d.target_vocabulary_id),
            d.previous_concept_id, csv_safe(d.suggestion_source), d.confidence_score,
            csv_safe(d.user), d.created_at.isoformat() if d.created_at else "",
        ])
    output.seek(0)

    filename = f"mapping_history_{cdm_name}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ──── 7. Reference Codebooks ────

@router.post("/reference/upload")
async def upload_reference(
    name: str = Form(...),
    domain: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a CSV reference codebook (code, description)."""
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    # Auto-detect delimiter
    first_line = text.split("\n")[0]
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if reader.fieldnames is None or len(reader.fieldnames) < 2:
        raise HTTPException(status_code=400, detail="CSV must have at least 2 columns")

    fields = [f.strip().lower() for f in reader.fieldnames]
    # Detect code column
    code_col = None
    for candidate in ["ccam", "code_ccam", "code_cim", "cim", "code_acte", "code"]:
        if candidate in fields:
            code_col = reader.fieldnames[fields.index(candidate)]
            break
    if not code_col:
        code_col = reader.fieldnames[0]

    # Detect description column
    desc_col = None
    for candidate in ["description", "libelle", "libellé", "label", "nom", "designation", "désignation"]:
        if candidate in fields:
            desc_col = reader.fieldnames[fields.index(candidate)]
            break
    if not desc_col:
        desc_col = reader.fieldnames[1]

    # Delete existing entries for this name
    db.query(ReferenceCodebook).filter(ReferenceCodebook.name == name).delete()
    db.flush()

    # Insert new entries (deduplicate by code)
    now = datetime.now(timezone.utc)
    seen_codes = set()
    count = 0
    for row in reader:
        code = (row.get(code_col) or "").strip()
        desc = (row.get(desc_col) or "").strip()
        if code and desc and code not in seen_codes:
            seen_codes.add(code)
            db.add(ReferenceCodebook(
                name=name, domain=domain, code=code,
                description=desc, uploaded_at=now,
            ))
            count += 1

    db.commit()
    return {"name": name, "domain": domain, "count": count}


@router.get("/reference")
def list_references(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List all loaded reference codebooks."""
    base_q = (
        db.query(
            ReferenceCodebook.name,
            ReferenceCodebook.domain,
            func.count(ReferenceCodebook.id).label("count"),
            func.max(ReferenceCodebook.uploaded_at).label("uploaded_at"),
        )
        .group_by(ReferenceCodebook.name, ReferenceCodebook.domain)
    )
    total = base_q.count()
    results = base_q.offset(offset).limit(limit).all()
    return {
        "references": [
            {
                "name": r.name, "domain": r.domain,
                "count": r.count,
                "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None,
            }
            for r in results
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.delete("/reference/{name}")
def delete_reference(name: str, db: Session = Depends(get_db)):
    """Delete a reference codebook by name."""
    deleted = db.query(ReferenceCodebook).filter(ReferenceCodebook.name == name).delete()
    db.commit()
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"Reference '{name}' not found")
    return {"deleted": deleted, "name": name}


# ──── 5.9 SapBERT Pre-computed Mappings ────

@router.post("/sapbert/upload")
async def upload_sapbert(
    domain: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload SapBERT mapping results CSV (from sapbert_mapping.py output)."""
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    delimiter = ";" if text.split("\n")[0].count(";") > text.split("\n")[0].count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

    # Delete existing entries for this domain
    db.query(SapbertMapping).filter(SapbertMapping.domain == domain).delete()
    db.flush()

    now = datetime.now(timezone.utc)
    count = 0
    for row in reader:
        source_code = (row.get("source_code") or "").strip()
        target_concept_id = row.get("target_concept_id", "")
        if not source_code or not target_concept_id:
            continue
        try:
            db.add(SapbertMapping(
                domain=domain,
                source_code=source_code,
                source_name=(row.get("source_name") or "").strip(),
                rank=int(row.get("rank", 1)),
                target_concept_id=int(target_concept_id),
                target_concept_code=(row.get("target_concept_code") or "").strip(),
                target_concept_name=(row.get("target_concept_name") or "").strip(),
                target_vocabulary_id=(row.get("target_vocabulary_id") or "").strip(),
                similarity=float(row.get("similarity", 0)),
                uploaded_at=now,
            ))
            count += 1
        except (ValueError, TypeError) as e:
            logger.warning("Skipping SapBERT row: %s", e)
            continue

    db.commit()
    return {"domain": domain, "count": count}


@router.get("/sapbert")
def list_sapbert(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List loaded SapBERT mapping sets."""
    base_q = (
        db.query(
            SapbertMapping.domain,
            func.count(SapbertMapping.id).label("count"),
            func.count(func.distinct(SapbertMapping.source_code)).label("source_count"),
            func.max(SapbertMapping.uploaded_at).label("uploaded_at"),
        )
        .group_by(SapbertMapping.domain)
    )
    total = base_q.count()
    results = base_q.offset(offset).limit(limit).all()
    return {
        "sapbert_sets": [
            {
                "domain": r.domain,
                "count": r.count,
                "source_count": r.source_count,
                "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None,
            }
            for r in results
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.delete("/sapbert/{domain}")
def delete_sapbert(domain: str, db: Session = Depends(get_db)):
    """Delete SapBERT mappings for a domain."""
    deleted = db.query(SapbertMapping).filter(SapbertMapping.domain == domain).delete()
    db.commit()
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"No SapBERT data for domain '{domain}'")
    return {"deleted": deleted, "domain": domain}
