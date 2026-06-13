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
from db.models import CdmConfig, AnalysisSettings, AnalysisSnapshot, MappingDecision, ReferenceCodebook, SapbertMapping, SapbertDomainState
from utils.notifications import notify
from db.omop_connector import get_omop_connection
from utils.crypto import decrypt_password
from config import DEFAULT_OMOP_SCHEMA, DOMAIN_CONFIG
from modules.mapping.suggest import suggest_mappings, suggest_batch
from utils.csv_safety import csv_safe
from utils.sql_safety import safe_identifier
from utils.rate_limit import limiter
from utils.cdm_helper import check_cdm_access, get_domain_config, build_schema_map, raise_source_value_cache_missing

logger = logging.getLogger(__name__)


def _get_username(request: Request) -> str:
    """Extract authenticated username from request. Raises 401 if not resolved."""
    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "")
    if not username or username in ("anonymous", "system"):
        raise HTTPException(status_code=401, detail="Utilisateur non authentifié")
    return username


def _get_consensus_decisions(db: Session, cdm_name: str, domain: str) -> list:
    """Return only decisions that have consensus (2+ distinct users approved same source_value → target).

    Returns one representative MappingDecision per consensus group.
    """
    from sqlalchemy import distinct

    # Find (source_value, target_concept_id) pairs with 2+ distinct users
    consensus_pairs = (
        db.query(
            MappingDecision.source_value,
            MappingDecision.target_concept_id,
        )
        .filter(
            MappingDecision.cdm_name == cdm_name,
            MappingDecision.domain == domain,
            MappingDecision.action.in_(["approved", "modified"]),
            MappingDecision.target_concept_id.isnot(None),
        )
        .group_by(MappingDecision.source_value, MappingDecision.target_concept_id)
        .having(func.count(distinct(MappingDecision.user)) >= 2)
        .all()
    )

    if not consensus_pairs:
        return []

    # For each consensus pair, get one representative decision (most recent)
    results = []
    for sv, tid in consensus_pairs:
        decision = (
            db.query(MappingDecision)
            .filter(
                MappingDecision.cdm_name == cdm_name,
                MappingDecision.domain == domain,
                MappingDecision.source_value == sv,
                MappingDecision.target_concept_id == tid,
                MappingDecision.action.in_(["approved", "modified"]),
            )
            .order_by(desc(MappingDecision.created_at))
            .first()
        )
        if decision:
            results.append(decision)

    return results


def _annotate_pending_decisions(db: Session, cdm_name: str, domain: str, items: list[dict]) -> None:
    """Fill `mapped_concept_*` from OPAL mapping decisions for source values
    still unmapped in the CDM, and tag them with `pending=True`.

    Mirrors `_annotate_pending_mappings` in concept explorer: CDM mapping wins,
    OPAL pending decisions only fill the gaps. `pending_user`/`pending_at` are
    kept as extras for the Manual-tab "Already decided in OPAL" banner.
    """
    if not items:
        return
    for r in items:
        r.setdefault("pending", False)
    targets = [r for r in items if not r.get("mapped_concept_id")]
    if not targets:
        return
    source_values = [r["source_value"] for r in targets]
    rows = (
        db.query(MappingDecision)
        .filter(
            MappingDecision.cdm_name == cdm_name,
            MappingDecision.domain == domain,
            MappingDecision.action.in_(["approved", "modified"]),
            MappingDecision.target_concept_id.isnot(None),
            MappingDecision.source_value.in_(source_values),
        )
        .order_by(MappingDecision.created_at.desc())
        .all()
    )
    latest: dict[str, MappingDecision] = {}
    for d in rows:
        if d.source_value not in latest:
            latest[d.source_value] = d
    for r in targets:
        d = latest.get(r["source_value"])
        if d:
            r["mapped_concept_id"] = d.target_concept_id
            r["mapped_concept_name"] = d.target_concept_name or ""
            r["mapped_vocabulary_id"] = d.target_vocabulary_id or ""
            r["mapped_standard_concept"] = None
            r["pending"] = True
            r["pending_user"] = d.user
            r["pending_at"] = d.created_at.isoformat() if d.created_at else None


def _cdm_concept_ids_by_sv(db: Session, cdm_name: str, pairs: set[tuple[str, str]]) -> dict[tuple[str, str], list[int]]:
    """Return {(domain, source_value): [distinct non-zero CDM concept_ids]} from the
    pre-computed SourceValueCache (app DB — no live CDM query)."""
    if not pairs:
        return {}
    from db.models import SourceValueCache

    svs = list({sv for _d, sv in pairs})
    domains = list({d for d, _sv in pairs})
    rows = (
        db.query(SourceValueCache.domain, SourceValueCache.source_value, SourceValueCache.mapped_concept_id)
        .filter(
            SourceValueCache.cdm_name == cdm_name,
            SourceValueCache.domain.in_(domains),
            SourceValueCache.source_value.in_(svs),
            SourceValueCache.mapped_concept_id.isnot(None),
            SourceValueCache.mapped_concept_id != 0,
        )
        .distinct()
        .all()
    )
    out: dict[tuple[str, str], set] = {}
    for d, sv, cid in rows:
        if (d, sv) in pairs:
            out.setdefault((d, sv), set()).add(cid)
    return {k: sorted(v) for k, v in out.items()}


def _annotate_cdm_concept_counts(db: Session, cdm_name: str, items: list[dict]) -> None:
    """Annotate each item with ``cdm_concepts`` (count) and ``cdm_concept_ids`` (list):
    the distinct non-zero concept_ids currently mapped to its (domain, source_value)
    in the CDM. Drives the History badges (synced / different target / 1→N) without
    scanning the CDM on every load.
    """
    if not items:
        return
    for r in items:
        r["cdm_concepts"] = 0
        r["cdm_concept_ids"] = []
    pairs = {(r["domain"], r["source_value"]) for r in items}
    ids_by = _cdm_concept_ids_by_sv(db, cdm_name, pairs)
    for r in items:
        ids = ids_by.get((r["domain"], r["source_value"]), [])
        r["cdm_concepts"] = len(ids)
        r["cdm_concept_ids"] = ids


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
    enable_exact: bool = True
    enable_relationship: bool = True
    enable_ingredient: bool = True
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
    target_cdms: list[str] = Field(default_factory=list)  # CDMs to apply to. Defaults to [cdm_name].


class SyncRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1, max_length=255)
    domain: str | None = Field(default=None, max_length=100)
    source_values: list[str] | None = Field(default=None, max_length=5000)


# ──── Helpers ────

def _get_cdm_conn(db: Session, cdm_name: str):
    cdm = db.query(CdmConfig).filter(CdmConfig.name == cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{cdm_name}' not found")
    password = decrypt_password(cdm.db_password_encrypted)
    try:
        conn = get_omop_connection(cdm.db_host, cdm.db_port, cdm.db_name, cdm.db_user, password, db_type=getattr(cdm, "db_type", None) or "postgresql")
    except Exception as e:
        logger.exception("Cannot connect to CDM '%s'", cdm.name)
        raise HTTPException(status_code=502, detail="Cannot connect to CDM database")
    return cdm, conn


def _get_schema(db: Session, cdm: CdmConfig):
    settings = db.query(AnalysisSettings).filter(
        AnalysisSettings.cdm_name == cdm.name
    ).first()
    return build_schema_map(cdm, settings)


# ──── 5.1 Mapping Dashboard ────

@router.get("/dashboard/{cdm_name}")
def mapping_dashboard(cdm_name: str, db: Session = Depends(get_db)):
    """
    Mapping rates by domain with record counts.
    Uses latest quality analysis snapshots per domain, enriched with the
    decision pipeline (consensus-aware): validated / pending / rejected /
    to-push counts per domain, staleness vs the snapshot, and the list of
    domains never analyzed.
    """
    from sqlalchemy import distinct

    # P44 fix: single query with DISTINCT ON instead of N+1 loop
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

    # ── Decision pipeline per domain (consensus-aware, same rule as History) ──
    # One aggregate per (domain, source_value, target): user count decides
    # pending vs validated; any synced row marks the pair as already in the CDM.
    pair_rows = (
        db.query(
            MappingDecision.domain,
            MappingDecision.source_value,
            MappingDecision.target_concept_id,
            func.count(distinct(MappingDecision.user)).label("users"),
            func.max(MappingDecision.synced).label("synced"),
            func.max(MappingDecision.created_at).label("last_at"),
        )
        .filter(
            MappingDecision.cdm_name == cdm_name,
            MappingDecision.action.in_(["approved", "modified"]),
            MappingDecision.target_concept_id.isnot(None),
        )
        .group_by(
            MappingDecision.domain,
            MappingDecision.source_value,
            MappingDecision.target_concept_id,
        )
        .all()
    )
    pipeline_by_domain: dict[str, dict] = {}
    for r in pair_rows:
        p = pipeline_by_domain.setdefault(
            r.domain,
            {"validated": 0, "pending": 0, "to_push": 0, "rejected": 0},
        )
        if r.users >= 2:
            p["validated"] += 1
            if not r.synced:
                p["to_push"] += 1
        else:
            p["pending"] += 1

    rejected_rows = (
        db.query(
            MappingDecision.domain,
            func.count(distinct(MappingDecision.source_value)).label("n"),
        )
        .filter(
            MappingDecision.cdm_name == cdm_name,
            MappingDecision.action == "rejected",
        )
        .group_by(MappingDecision.domain)
        .all()
    )
    for r in rejected_rows:
        p = pipeline_by_domain.setdefault(
            r.domain,
            {"validated": 0, "pending": 0, "to_push": 0, "rejected": 0},
        )
        p["rejected"] = r.n

    # Staleness: the snapshot rates measure the CDM itself, so only an actual
    # push to this CDM after the snapshot makes them outdated (decisions alone
    # don't change the CDM until they are applied).
    from db.models import MappingApplyLog
    push_rows = (
        db.query(
            MappingApplyLog.domain,
            func.max(MappingApplyLog.applied_at).label("last_push"),
        )
        .filter(MappingApplyLog.target_cdm_name == cdm_name)
        .group_by(MappingApplyLog.domain)
        .all()
    )
    last_push_by_domain = {r.domain: r.last_push for r in push_rows}

    domains_data = []
    for snapshot in latest_snapshots:
        results = snapshot.results
        mapping = results.get("mapping", {})
        terms = mapping.get("terms", {})
        rows = mapping.get("rows", {})
        p = pipeline_by_domain.get(snapshot.domain)
        last_push = last_push_by_domain.get(snapshot.domain)
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
            "decisions": {
                "validated": p["validated"] if p else 0,
                "pending": p["pending"] if p else 0,
                "rejected": p["rejected"] if p else 0,
                "to_push": p["to_push"] if p else 0,
            },
            # Mappings pushed to the CDM after the snapshot → displayed rates predate them
            "stale": bool(
                last_push and snapshot.created_at and last_push > snapshot.created_at
            ),
        })

    # Domains without any quality snapshot still carry their decision pipeline
    # (decisions are not tied to quality results) — only the rate/volume
    # columns need a snapshot.
    analyzed = {s.domain for s in latest_snapshots}
    never_analyzed = []
    for d in DOMAIN_CONFIG.keys():
        if d in analyzed:
            continue
        p = pipeline_by_domain.get(d)
        never_analyzed.append({
            "domain": d,
            "decisions": {
                "validated": p["validated"] if p else 0,
                "pending": p["pending"] if p else 0,
                "rejected": p["rejected"] if p else 0,
                "to_push": p["to_push"] if p else 0,
            },
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

    # Global pipeline KPIs (terms = distinct source_value→target pairs)
    pipeline = {
        "unmapped_terms": sum(d["unmapped_terms"] for d in domains_data),
        "pending_terms": sum(p["pending"] for p in pipeline_by_domain.values()),
        "validated_terms": sum(p["validated"] for p in pipeline_by_domain.values()),
        "to_push_terms": sum(p["to_push"] for p in pipeline_by_domain.values()),
    }

    return {
        "cdm_name": cdm_name,
        "domains": domains_data,
        "never_analyzed": never_analyzed,
        "decisions_summary": decisions_summary,
        "pipeline": pipeline,
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

# Sources actually emitted by the current suggestion engine (suggest.py +
# SapBERT). Human origins (manual, history, bulk, rollback*) and retired
# strategies (keyword, fuzzy, contextual) are excluded from strategy
# performance — the table evaluates the engine, not the users.
SUGGESTION_STRATEGY_SOURCES = ["exact", "relationship", "ingredient", "synonym", "sapbert"]


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
    Only covers the strategies of the current suggestion engine.
    """
    # P45 fix: push aggregation to SQL instead of loading all decisions into memory
    from sqlalchemy import case
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
        MappingDecision.suggestion_source.in_(SUGGESTION_STRATEGY_SOURCES),
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

    # ── Try cache first ──
    from db.models import SourceValueCache
    from sqlalchemy import or_, func as sa_func

    cache_exists = db.query(SourceValueCache.id).filter(
        SourceValueCache.cdm_name == cdm_name,
        SourceValueCache.domain == domain,
    ).first()

    if cache_exists:
        query = db.query(
            SourceValueCache.source_value,
            SourceValueCache.source_name,
            SourceValueCache.source_atc,
            sa_func.sum(SourceValueCache.n_records).label("n_records"),
            sa_func.sum(SourceValueCache.n_persons).label("n_persons"),
            SourceValueCache.mapped_concept_id,
            SourceValueCache.mapped_concept_name,
            SourceValueCache.mapped_vocabulary_id,
            SourceValueCache.mapped_standard_concept,
        ).filter(
            SourceValueCache.cdm_name == cdm_name,
            SourceValueCache.domain == domain,
        )
        if not include_mapped:
            query = query.filter(
                or_(SourceValueCache.mapped_concept_id == 0, SourceValueCache.mapped_concept_id.is_(None))
            )
        if search:
            from utils.text_search import iaccent_ilike
            search_clauses = [
                iaccent_ilike(SourceValueCache.source_value, f"%{search}%"),
                iaccent_ilike(SourceValueCache.source_name, f"%{search}%"),
                iaccent_ilike(SourceValueCache.source_atc, f"%{search}%"),
            ]
            query = query.filter(or_(*search_clauses))
        query = query.group_by(
            SourceValueCache.source_value, SourceValueCache.source_name, SourceValueCache.source_atc,
            SourceValueCache.mapped_concept_id, SourceValueCache.mapped_concept_name,
            SourceValueCache.mapped_vocabulary_id, SourceValueCache.mapped_standard_concept,
        )

        total_q = query.subquery()
        total = db.query(sa_func.count()).select_from(total_q).scalar() or 0

        offset = (page - 1) * page_size
        rows_q = query.order_by(sa_func.sum(SourceValueCache.n_records).desc()).offset(offset).limit(page_size).all()
        rows = [
            {"source_value": r.source_value, "source_name": r.source_name or "",
             "source_atc": r.source_atc or "",
             "n_records": int(r.n_records), "n_persons": int(r.n_persons),
             "mapped_concept_id": r.mapped_concept_id,
             "mapped_concept_name": r.mapped_concept_name,
             "mapped_vocabulary_id": r.mapped_vocabulary_id,
             "mapped_standard_concept": r.mapped_standard_concept}
            for r in rows_q
        ]
        _annotate_pending_decisions(db, cdm_name, domain, rows)
        return {"items": rows, "total": total, "page": page, "page_size": page_size, "cached": True}

    # Source-value listing is backed exclusively by the app-DB SourceValueCache
    # (engine-agnostic, no live-CDM fallback). If we reach here the cache for this
    # (cdm, domain) has not been built yet.
    raise_source_value_cache_missing(cdm_name, domain)


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
        dialect = conn.dialect
        with dialect.dict_cursor(conn) as cur:
            dialect.execute(cur, f"""
                SELECT concept_id, concept_name, concept_code,
                       vocabulary_id, domain_id, standard_concept, concept_class_id
                FROM {schema.t('concept')}
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

def _sapbert_scope(db: Session, cdm_name: str, domain: str) -> tuple[bool, str | None]:
    """Resolve how to read SapBERT rows for (cdm, domain), honoring the per-domain toggle.

    Returns (enabled, cdm_filter):
      - built in-app (a SapbertDomainState row exists): use this CDM's rows only,
        and only if the toggle is on -> (state.enabled, cdm_name).
      - never built: fall back to legacy global rows (cdm_name IS NULL), on by
        default -> (True, None).
    cdm_filter None means "match the legacy NULL-cdm_name rows".
    """
    state = (
        db.query(SapbertDomainState)
        .filter(SapbertDomainState.cdm_name == cdm_name, SapbertDomainState.domain == domain)
        .first()
    )
    if state is None:
        return True, None
    return bool(state.enabled), cdm_name


def _filter_sapbert_cdm(query, cdm_filter: str | None):
    """Apply the cdm_name scope: a specific CDM, or the legacy NULL rows."""
    if cdm_filter is None:
        return query.filter(SapbertMapping.cdm_name.is_(None))
    return query.filter(SapbertMapping.cdm_name == cdm_filter)


def _get_sapbert_suggestions(db: Session, source_value: str, domain: str, cdm_name: str) -> list[dict]:
    """Look up pre-computed SapBERT suggestions for a source value (per CDM + toggle)."""
    enabled, cdm_filter = _sapbert_scope(db, cdm_name, domain)
    if not enabled:
        return []
    query = db.query(SapbertMapping).filter(
        SapbertMapping.domain == domain,
        SapbertMapping.source_code == source_value,
    )
    rows = _filter_sapbert_cdm(query, cdm_filter).order_by(SapbertMapping.rank).all()
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
    # Prefer EN codebooks for mapping (needed for fuzzy/keyword match against OMOP EN vocabulary)
    if not source_name:
        ref = db.query(ReferenceCodebook.description).filter(
            ReferenceCodebook.domain == req.domain,
            ReferenceCodebook.code == req.source_value,
            ReferenceCodebook.name.endswith("_EN"),
        ).first()
        if not ref:
            ref = db.query(ReferenceCodebook.description).filter(
                ReferenceCodebook.domain == req.domain,
                ReferenceCodebook.code == req.source_value,
            ).first()
        if ref:
            source_name = ref.description

    # Check SapBERT pre-computed suggestions first (per CDM + per-domain toggle)
    sapbert_suggs = _get_sapbert_suggestions(db, req.source_value, req.domain, req.cdm_name)

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
    username = _get_username(request)

    cdm, conn = _get_cdm_conn(db, req.cdm_name)
    schema = _get_schema(db, cdm)
    cfg = get_domain_config(conn, schema, req.domain)
    # Filter already-decided terms for THIS USER only (per-user mapping workflow)
    approved_svs = [
        r[0] for r in
        db.query(MappingDecision.source_value)
        .filter(
            MappingDecision.cdm_name == req.cdm_name,
            MappingDecision.domain == req.domain,
            MappingDecision.user == username,
            MappingDecision.action.in_(["approved", "modified"]),
        ).all()
    ]

    # SapBERT mappings are now fetched lazily in the worker after we know
    # which terms to process (P46 fix: avoid loading 100K+ rows upfront).
    sapbert_domain = req.domain

    # Pre-fetch reference codebooks — prefer EN for mapping (fuzzy/keyword match against OMOP EN vocab)
    ref_rows = db.query(ReferenceCodebook.code, ReferenceCodebook.description, ReferenceCodebook.name).filter(
        ReferenceCodebook.domain == req.domain
    ).all()
    ref_map: dict[str, str] = {}
    for r in ref_rows:
        if r.name.endswith("_EN"):
            ref_map[r.code] = r.description  # EN always wins
    for r in ref_rows:
        if r.code not in ref_map:
            ref_map[r.code] = r.description  # fallback for codes not in EN

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
    enable_exact = req.enable_exact
    enable_relationship = req.enable_relationship
    enable_ingredient = req.enable_ingredient
    enable_sapbert = req.enable_sapbert

    def _worker():
        try:
            dialect = conn.dialect
            _table = safe_identifier(cfg["table"])
            full_table = f"{schema.t(_table)}"
            sv_col = safe_identifier(cfg["source_value"])
            concept_col = safe_identifier(cfg["concept_id"])
            sn_col = safe_identifier(cfg["source_name"]) if cfg.get("source_name") else None

            with dialect.dict_cursor(conn) as cur:
                select_cols = [f"t.{sv_col} AS source_value"]
                if sn_col:
                    select_cols.append(f"MAX(t.{sn_col}) AS source_name")
                else:
                    select_cols.append("'' AS source_name")

                where_clauses = [f"(t.{concept_col} = 0 OR t.{concept_col} IS NULL)"]
                params: list = []
                if approved_svs:
                    frag, frag_params = dialect.not_in_list(f"t.{sv_col}", approved_svs)
                    where_clauses.append(frag)
                    params.extend(frag_params)

                sql = f"""
                    SELECT {', '.join(select_cols)}, COUNT(*) AS n_records
                    FROM {full_table} t
                    WHERE {' AND '.join(where_clauses)}
                    GROUP BY t.{sv_col}
                    ORDER BY COUNT(*) DESC
                    {dialect.limit_offset(str(int(limit)), '0')}
                """
                dialect.execute(cur, sql, params)
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
                    _enabled, _cdm_filter = _sapbert_scope(_db, req.cdm_name, sapbert_domain)
                    if _enabled:
                        _q = _db.query(SapbertMapping).filter(
                            SapbertMapping.domain == sapbert_domain,
                            SapbertMapping.source_code.in_(all_svs),
                        )
                        sapbert_rows = (
                            _filter_sapbert_cdm(_q, _cdm_filter)
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

            # Run the deterministic SQL strategies (exact / Maps to / ingredient)
            # on ALL terms per their toggles, then merge SapBERT on top (SapBERT
            # first, SQL deduped by concept_id). The strategies are independent.
            with _suggestions_lock:
                if _active_suggestions.get(task_id, {}).get("cancelled"):
                    return

            sql_map: dict[str, list[dict]] = {}
            if enable_exact or enable_relationship or enable_ingredient:
                for r in suggest_batch(conn, terms, domain, schema,
                                       enable_exact=enable_exact,
                                       enable_relationship=enable_relationship,
                                       enable_ingredient=enable_ingredient):
                    sql_map[r["source_value"]] = r.get("suggestions", [])

            results = []
            for t in terms:
                sv = t["source_value"]
                merged = list(sapbert_map.get(sv, []))
                seen = {s["concept_id"] for s in merged}
                for s in sql_map.get(sv, []):
                    if s["concept_id"] not in seen:
                        merged.append(s)
                        seen.add(s["concept_id"])
                results.append({
                    "source_value": sv,
                    "source_name": t.get("source_name", ""),
                    "suggestions": merged,
                })

            # Warnings about limited strategies (exact / Maps to / ingredient / SapBERT).
            # Based on whether the terms actually carry a label (from the CDM column
            # OR a reference codebook), not on whether a CDM source_name column exists.
            warnings = []
            has_labels = any(t.get("source_name") for t in terms)
            if not has_labels:
                # No label -> "Maps to" and "Ingredient" can't run; only Exact
                # (and SapBERT, if built) apply.
                warnings.append("source_name_missing")
            if enable_sapbert and not sapbert_map:
                warnings.append("no_sapbert_embeddings")

            with _suggestions_lock:
                if task_id in _active_suggestions:
                    _active_suggestions[task_id]["status"] = "done"
                    _active_suggestions[task_id]["results"] = results
                    _active_suggestions[task_id]["warnings"] = warnings

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
        resp["warnings"] = entry.get("warnings", [])
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

    username = _get_username(request)

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
        user=username,
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

    username = _get_username(request)

    if req.source_values:
        # Get existing source values for THIS USER only
        existing = set(
            r[0] for r in
            db.query(MappingDecision.source_value)
            .filter(
                MappingDecision.cdm_name == req.cdm_name,
                MappingDecision.domain == req.domain,
                MappingDecision.user == username,
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
                    user=username,
                )
                for sv in new_values
            ])
            db.commit()
        count = len(new_values)
    else:
        count = 0

    return {"action": req.action, "count": count}


# ──── 5.5 Apply Mapping ────

# Preflight warning flags (apply/export). A source value carrying ANY flag is
# excluded from the in-place push (only concept_id = 0 may be pushed) but is
# still kept in the STCM export, where the ETL handles 1→N / cross-domain.
WARN_MULTIPLE_TARGETS_OPAL = "multiple_targets_opal"    # ≥2 distinct consensus targets for one source value
WARN_ALREADY_MAPPED_CDM = "already_mapped_cdm"          # source value already mapped in the CDM (concept_id ≠ 0)
WARN_MULTIPLE_CONCEPTS_CDM = "multiple_concepts_cdm"    # source value mapped to ≥2 distinct concepts in the CDM


def _compute_mapping_warnings(conn, full_table: str, sv_col: str, concept_col: str, decisions: list) -> dict:
    """Preflight check before push/export.

    Flags each source value that is unsafe to push in place. Returns
    ``{"items": [...flagged only...], "counts": {...}, "flagged": set(source_values)}``.

    A source value is flagged when:
      - A (``multiple_targets_opal``): it has ≥2 distinct consensus targets (1→N in OPAL decisions);
      - B (``already_mapped_cdm``): it is already mapped in the CDM (≥1 non-zero concept_id);
      - C (``multiple_concepts_cdm``): it maps to ≥2 distinct concepts in the CDM (materialised 1→N).

    Only codes with NO flag (i.e. currently unmapped, single consensus target) are pushable.
    """
    targets_by_sv: dict[str, set] = {}
    name_by_sv: dict[str, str] = {}
    for d in decisions:
        targets_by_sv.setdefault(d.source_value, set()).add(d.target_concept_id)
        if d.source_name and d.source_value not in name_by_sv:
            name_by_sv[d.source_value] = d.source_name

    source_values = list(targets_by_sv.keys())

    # B / C: distinct non-zero concept_ids currently in the CDM, per source value (one query)
    cdm_concepts: dict[str, int] = {}
    if source_values:
        dialect = conn.dialect
        sv_frag, sv_params = dialect.in_list(sv_col, source_values)
        with dialect.dict_cursor(conn) as cur:
            dialect.execute(
                cur,
                f"SELECT {sv_col} AS sv, "
                f"COUNT(DISTINCT CASE WHEN {concept_col} IS NOT NULL AND {concept_col} <> 0 "
                f"THEN {concept_col} END) AS n_concepts "
                f"FROM {full_table} WHERE {sv_frag} "
                f"GROUP BY {sv_col}",
                sv_params,
            )
            for row in cur.fetchall():
                cdm_concepts[row["sv"]] = int(row["n_concepts"] or 0)

    items: list[dict] = []
    flagged: set[str] = set()
    counts = {
        WARN_MULTIPLE_TARGETS_OPAL: 0,
        WARN_ALREADY_MAPPED_CDM: 0,
        WARN_MULTIPLE_CONCEPTS_CDM: 0,
    }
    for sv in source_values:
        flags: list[str] = []
        n_cdm = cdm_concepts.get(sv, 0)
        if len(targets_by_sv[sv]) >= 2:
            flags.append(WARN_MULTIPLE_TARGETS_OPAL)
            counts[WARN_MULTIPLE_TARGETS_OPAL] += 1
        if n_cdm >= 1:
            flags.append(WARN_ALREADY_MAPPED_CDM)
            counts[WARN_ALREADY_MAPPED_CDM] += 1
        if n_cdm >= 2:
            flags.append(WARN_MULTIPLE_CONCEPTS_CDM)
            counts[WARN_MULTIPLE_CONCEPTS_CDM] += 1
        if flags:
            flagged.add(sv)
            items.append({
                "source_value": sv,
                "source_name": name_by_sv.get(sv, ""),
                "flags": flags,
                "opal_targets": sorted(t for t in targets_by_sv[sv] if t is not None),
                "cdm_concepts": n_cdm,
            })
    items.sort(key=lambda x: x["source_value"])
    counts["total_flagged"] = len(flagged)
    return {"items": items, "counts": counts, "flagged": flagged}


def _redundant_svs_live(conn, full_table: str, sv_col: str, concept_col: str, decisions: list) -> set:
    """Source values already correctly in the CDM (mapped to exactly their single
    consensus target) or already marked synced. Nothing to push or re-export — the
    CDM already holds them — so they are dropped from preview and export."""
    redundant = {d.source_value for d in decisions if getattr(d, "synced", 0)}
    targets: dict[str, set] = {}
    for d in decisions:
        targets.setdefault(d.source_value, set()).add(d.target_concept_id)
    svs = list(targets.keys())
    cdm_ids: dict[str, set] = {}
    if svs:
        dialect = conn.dialect
        sv_frag, sv_params = dialect.in_list(sv_col, svs)
        with dialect.dict_cursor(conn) as cur:
            dialect.execute(
                cur,
                f"SELECT {sv_col} AS sv, {concept_col} AS cid FROM {full_table} "
                f"WHERE {sv_frag} AND {concept_col} IS NOT NULL AND {concept_col} <> 0 "
                f"GROUP BY {sv_col}, {concept_col}",
                sv_params,
            )
            for row in cur.fetchall():
                cdm_ids.setdefault(row["sv"], set()).add(row["cid"])
    for sv, tgts in targets.items():
        ids = cdm_ids.get(sv, set())
        if len(ids) == 1 and len(tgts) == 1 and ids == tgts:
            redundant.add(sv)
    return redundant


@router.post("/apply")
def apply_mapping(req: ApplyMappingRequest, request: Request, db: Session = Depends(get_db)):
    """
    Apply consensus mappings by UPDATE-ing concept_id columns in CDM clinical tables.
    Logs every UPDATE in MappingApplyLog for rollback.
    """
    import uuid
    from db.models import MappingApplyLog

    check_cdm_access(request, req.cdm_name)
    username = _get_username(request)

    decisions = _get_consensus_decisions(db, req.cdm_name, req.domain)
    if not decisions:
        return {"message": "No consensus mappings to apply", "count": 0, "rows": []}

    # Build STCM rows for response (always returned for compat / display)
    stcm_rows = [
        {
            "source_code": d.source_value,
            "source_code_description": d.source_name or d.source_value,
            "target_concept_id": d.target_concept_id,
            "target_vocabulary_id": d.target_vocabulary_id or "SNOMED",
        }
        for d in decisions
    ]

    if not req.write_to_cdm:
        return {"count": len(stcm_rows), "written_to_cdm": False, "rows": stcm_rows}

    # ── Write to CDM(s): UPDATE clinical table directly ──
    cfg = DOMAIN_CONFIG.get(req.domain)
    if not cfg:
        raise HTTPException(status_code=400, detail=f"Unknown domain: {req.domain}")
    table_name = cfg["table"]
    sv_col_name = cfg.get("source_value")
    concept_col_name = cfg["concept_id"]
    if not sv_col_name:
        raise HTTPException(status_code=400, detail=f"Domain {req.domain} has no source_value column")

    table = safe_identifier(table_name)
    sv_col = safe_identifier(sv_col_name)
    concept_col = safe_identifier(concept_col_name)

    # Targets default to source CDM
    target_cdms = req.target_cdms or [req.cdm_name]
    # Check access on all targets
    for tcdm in target_cdms:
        check_cdm_access(request, tcdm)

    batch_id = uuid.uuid4().hex
    per_cdm_results = {}
    synced_svs: set[str] = set()  # source values pushed into the source CDM → mark synced

    for tcdm in target_cdms:
        try:
            cdm_obj, conn = _get_cdm_conn(db, tcdm)
            schema = _get_schema(db, cdm_obj)
            full_table = f"{schema.t(table)}"
            total_updated = 0
            try:
                # Preflight: only unmapped, single-target codes are pushed.
                # Flagged codes (already mapped / 1→N) are skipped — they go via export.
                warnings = _compute_mapping_warnings(conn, full_table, sv_col, concept_col, decisions)
                flagged = warnings["flagged"]
                pushed = 0
                skipped = 0
                dialect = conn.dialect
                with conn.cursor() as cur:
                    for d in decisions:
                        if d.source_value in flagged:
                            skipped += 1
                            continue
                        # Snapshot previous values per (source_value, previous concept_id)
                        dialect.execute(
                            cur,
                            f"SELECT {concept_col} AS prev_id, COUNT(*) AS n "
                            f"FROM {full_table} WHERE {sv_col} = %(sv)s "
                            f"GROUP BY {concept_col}",
                            {"sv": d.source_value},
                        )
                        snapshot = cur.fetchall()
                        for prev_id, n in snapshot:
                            log = MappingApplyLog(
                                batch_id=batch_id,
                                source_cdm_name=req.cdm_name,
                                target_cdm_name=tcdm,
                                domain=req.domain,
                                table_name=table_name,
                                column_name=concept_col_name,
                                source_value=d.source_value,
                                previous_concept_id=prev_id,
                                new_concept_id=d.target_concept_id,
                                row_count=n,
                                applied_by=username,
                            )
                            db.add(log)
                        # UPDATE only unmapped rows (concept_id = 0/NULL) — defence in depth:
                        # a pushable code is fully unmapped, so this never overwrites a mapping.
                        dialect.execute(
                            cur,
                            f"UPDATE {full_table} SET {concept_col} = %(target)s "
                            f"WHERE {sv_col} = %(sv)s AND ({concept_col} = 0 OR {concept_col} IS NULL)",
                            {"target": d.target_concept_id, "sv": d.source_value},
                        )
                        total_updated += cur.rowcount
                        pushed += 1
                        # Pushed into the source CDM → now in sync with it
                        if tcdm == req.cdm_name:
                            synced_svs.add(d.source_value)
                    conn.commit()
                db.commit()
                per_cdm_results[tcdm] = {
                    "updated_rows": total_updated,
                    "decisions": pushed,
                    "skipped": skipped,
                    "skipped_codes": warnings["counts"]["total_flagged"],
                }
            except Exception as e:
                conn.rollback()
                db.rollback()
                logger.exception("Apply mapping failed for CDM %s", tcdm)
                per_cdm_results[tcdm] = {"error": str(e)}
            finally:
                conn.close()
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Cannot connect to CDM %s for apply", tcdm)
            per_cdm_results[tcdm] = {"error": str(e)}

    # Auto-mark pushed decisions as synced (now in the source CDM with the same target)
    if synced_svs:
        db.query(MappingDecision).filter(
            MappingDecision.cdm_name == req.cdm_name,
            MappingDecision.domain == req.domain,
            MappingDecision.source_value.in_(list(synced_svs)),
            MappingDecision.action.in_(["approved", "modified"]),
        ).update({MappingDecision.synced: 1}, synchronize_session=False)

    notify(
        db, username, "mapping_applied",
        title=f"Mapping appliqué : {req.domain}",
        message=f"Batch {batch_id[:8]} — {len(decisions)} mappings sur {len(target_cdms)} CDM(s).",
        link=f"/mapping?cdm={req.cdm_name}&domain={req.domain}",
        target_role="data-manager",
        item_id=f"{req.cdm_name}:{req.domain}",
    )
    db.commit()

    return {
        "count": len(stcm_rows),
        "written_to_cdm": True,
        "batch_id": batch_id,
        "per_cdm": per_cdm_results,
        "rows": stcm_rows,
    }


@router.post("/apply/rollback/{batch_id}")
def rollback_apply(batch_id: str, request: Request, db: Session = Depends(get_db)):
    """Rollback a previous mapping apply by batch_id — restore previous concept_ids."""
    from db.models import MappingApplyLog

    username = _get_username(request)
    logs = db.query(MappingApplyLog).filter(
        MappingApplyLog.batch_id == batch_id,
        MappingApplyLog.rolled_back == 0,
    ).all()
    if not logs:
        raise HTTPException(status_code=404, detail="Batch not found or already rolled back")

    # Group logs by target CDM
    per_cdm: dict[str, list] = {}
    for log in logs:
        per_cdm.setdefault(log.target_cdm_name, []).append(log)

    per_cdm_results = {}
    for tcdm, cdm_logs in per_cdm.items():
        check_cdm_access(request, tcdm)
        try:
            cdm_obj, conn = _get_cdm_conn(db, tcdm)
            schema = _get_schema(db, cdm_obj)
            try:
                dialect = conn.dialect
                with conn.cursor() as cur:
                    restored = 0
                    for log in cdm_logs:
                        table = safe_identifier(log.table_name)
                        col = safe_identifier(log.column_name)
                        cfg = DOMAIN_CONFIG.get(log.domain, {})
                        sv_col_name = cfg.get("source_value")
                        if not sv_col_name:
                            continue
                        sv_col = safe_identifier(sv_col_name)
                        full_table = f"{schema.t(table)}"
                        dialect.execute(
                            cur,
                            f"UPDATE {full_table} SET {col} = %(prev)s "
                            f"WHERE {sv_col} = %(sv)s AND {col} = %(new)s",
                            {"prev": log.previous_concept_id, "sv": log.source_value, "new": log.new_concept_id},
                        )
                        restored += cur.rowcount
                        log.rolled_back = 1
                    conn.commit()
                db.commit()
                per_cdm_results[tcdm] = {"restored_rows": restored}
            except Exception as e:
                conn.rollback()
                db.rollback()
                logger.exception("Rollback failed for CDM %s", tcdm)
                per_cdm_results[tcdm] = {"error": str(e)}
            finally:
                conn.close()
        except Exception as e:
            per_cdm_results[tcdm] = {"error": str(e)}

    return {"batch_id": batch_id, "per_cdm": per_cdm_results}


@router.get("/apply/batch/{batch_id}")
def apply_batch_detail(batch_id: str, db: Session = Depends(get_db)):
    """Return full per-source-value detail of an apply batch."""
    from db.models import MappingApplyLog

    rows = db.query(MappingApplyLog).filter(
        MappingApplyLog.batch_id == batch_id,
    ).order_by(MappingApplyLog.source_value, MappingApplyLog.previous_concept_id).all()

    if not rows:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Look up concept names from CDM if possible
    concept_names: dict[int, str] = {}
    target_cdm = rows[0].target_cdm_name
    concept_ids = set()
    for r in rows:
        if r.previous_concept_id:
            concept_ids.add(r.previous_concept_id)
        if r.new_concept_id:
            concept_ids.add(r.new_concept_id)
    if concept_ids:
        try:
            cdm_obj, conn = _get_cdm_conn(db, target_cdm)
            schema = _get_schema(db, cdm_obj)
            try:
                dialect = conn.dialect
                id_frag, id_params = dialect.in_list("concept_id", list(concept_ids))
                with conn.cursor() as cur:
                    dialect.execute(
                        cur,
                        f"SELECT concept_id, concept_name FROM {schema.t('concept')} "
                        f"WHERE {id_frag}",
                        id_params,
                    )
                    for cid, cname in cur.fetchall():
                        concept_names[cid] = cname
            finally:
                conn.close()
        except Exception:
            logger.warning("Failed to lookup concept names for batch detail", exc_info=True)

    return {
        "batch_id": batch_id,
        "source_cdm_name": rows[0].source_cdm_name,
        "target_cdm_name": rows[0].target_cdm_name,
        "domain": rows[0].domain,
        "table_name": rows[0].table_name,
        "column_name": rows[0].column_name,
        "applied_by": rows[0].applied_by,
        "applied_at": rows[0].applied_at.isoformat() if rows[0].applied_at else None,
        "rolled_back": bool(rows[0].rolled_back),
        "entries": [
            {
                "source_value": r.source_value,
                "previous_concept_id": r.previous_concept_id,
                "previous_concept_name": concept_names.get(r.previous_concept_id, ""),
                "new_concept_id": r.new_concept_id,
                "new_concept_name": concept_names.get(r.new_concept_id, ""),
                "row_count": r.row_count,
            }
            for r in rows
        ],
    }


@router.get("/apply/history/{cdm_name}")
def apply_history(cdm_name: str, db: Session = Depends(get_db)):
    """List apply batches that touched this CDM (as target)."""
    from db.models import MappingApplyLog

    rows = db.query(
        MappingApplyLog.batch_id,
        MappingApplyLog.domain,
        MappingApplyLog.applied_by,
        func.min(MappingApplyLog.applied_at).label("applied_at"),
        func.sum(MappingApplyLog.row_count).label("total_rows"),
        func.max(MappingApplyLog.rolled_back).label("rolled_back"),
    ).filter(
        MappingApplyLog.target_cdm_name == cdm_name,
    ).group_by(
        MappingApplyLog.batch_id, MappingApplyLog.domain, MappingApplyLog.applied_by,
    ).order_by(desc(func.min(MappingApplyLog.applied_at))).all()

    return {
        "batches": [
            {
                "batch_id": r.batch_id,
                "domain": r.domain,
                "applied_by": r.applied_by,
                "applied_at": r.applied_at.isoformat() if r.applied_at else None,
                "total_rows": int(r.total_rows or 0),
                "rolled_back": bool(r.rolled_back),
            }
            for r in rows
        ]
    }


@router.post("/apply/preview")
def apply_preview(req: ApplyMappingRequest, request: Request, db: Session = Depends(get_db)):
    """Preview impact of applying consensus mappings (2+ users agree)."""
    # cdm_name is in the JSON body, so the Keycloak middleware cannot see it — check here.
    check_cdm_access(request, req.cdm_name)
    _get_username(request)  # auth check

    decisions = _get_consensus_decisions(db, req.cdm_name, req.domain)

    _EMPTY_WARNINGS = {
        "items": [],
        "counts": {
            WARN_MULTIPLE_TARGETS_OPAL: 0,
            WARN_ALREADY_MAPPED_CDM: 0,
            WARN_MULTIPLE_CONCEPTS_CDM: 0,
            "total_flagged": 0,
        },
    }
    if not decisions or req.domain not in DOMAIN_CONFIG:
        return {"total_decisions": 0, "impacted_rows": 0, "impacted_persons": 0,
                "warnings": _EMPTY_WARNINGS, "n_total_codes": 0, "n_pushable_codes": 0, "n_redundant": 0}

    cdm, conn = _get_cdm_conn(db, req.cdm_name)
    schema = _get_schema(db, cdm)
    cfg = get_domain_config(conn, schema, req.domain)
    table = safe_identifier(cfg["table"])
    full_table = f"{schema.t(table)}"
    sv_col = safe_identifier(cfg["source_value"])
    concept_col = safe_identifier(cfg["concept_id"])

    try:
        dialect = conn.dialect
        # Drop codes already correctly in the CDM (synced / same target) — nothing to push or export
        redundant = _redundant_svs_live(conn, full_table, sv_col, concept_col, decisions)
        effective = [d for d in decisions if d.source_value not in redundant]
        source_values = [d.source_value for d in effective]
        if not source_values:
            row = None
            warnings = _compute_mapping_warnings(conn, full_table, sv_col, concept_col, [])
        else:
            sv_frag, sv_params = dialect.in_list(sv_col, source_values)
            with dialect.dict_cursor(conn) as cur:
                dialect.execute(cur, f"""
                    SELECT COUNT(*) AS n_rows, COUNT(DISTINCT person_id) AS n_persons
                    FROM {full_table}
                    WHERE {sv_frag}
                """, sv_params)
                row = cur.fetchone()
            # Warnings on the effective (non-redundant) set: already-mapped now means
            # "mapped to a DIFFERENT target" (the same-target ones were dropped as redundant).
            warnings = _compute_mapping_warnings(conn, full_table, sv_col, concept_col, effective)
    except Exception as e:
        logger.exception("Mapping preview query failed")
        raise HTTPException(status_code=500, detail="An internal error occurred during preview")
    finally:
        conn.close()

    n_total_codes = len(set(source_values))
    return {
        "total_decisions": len(effective),
        "impacted_rows": row["n_rows"] if row else 0,
        "impacted_persons": row["n_persons"] if row else 0,
        "warnings": {"items": warnings["items"], "counts": warnings["counts"]},
        "n_total_codes": n_total_codes,
        "n_pushable_codes": n_total_codes - warnings["counts"]["total_flagged"],
        "n_redundant": len(redundant),
    }


_DOMAIN_TO_TABLE = {
    "Condition": "CONDITION_OCCURRENCE",
    "Drug": "DRUG_EXPOSURE",
    "Procedure": "PROCEDURE_OCCURRENCE",
    "Measurement": "MEASUREMENT",
    "Observation": "OBSERVATION",
    "Device": "DEVICE_EXPOSURE",
    "Visit": "VISIT_OCCURRENCE",
    "Specimen": "SPECIMEN",
    "Death": "DEATH",
    "Note": "NOTE",
}

_DOMAIN_TO_SOURCE_VOCAB = {
    "Condition": "CIM-10",
    "Drug": "ATC",
    "Procedure": "CCAM",
}


@router.get("/apply/export/{cdm_name}/{domain}")
def export_stcm(cdm_name: str, domain: str, request: Request, db: Session = Depends(get_db)):
    """Export approved mappings as Usagi-compatible CSV (consensus only)."""
    from db.models import SourceValueCache

    decisions = _get_consensus_decisions(db, cdm_name, domain)

    # Look up frequency from source value cache
    freq_map = {}
    cache_rows = db.query(SourceValueCache.source_value, SourceValueCache.n_records).filter(
        SourceValueCache.cdm_name == cdm_name,
        SourceValueCache.domain == domain,
    ).all()
    for sv, n_rec in cache_rows:
        freq_map[sv] = freq_map.get(sv, 0) + (n_rec or 0)

    # Look up all users that approved each consensus pair
    users_map: dict[tuple, list[str]] = {}
    if decisions:
        all_users = db.query(
            MappingDecision.source_value,
            MappingDecision.target_concept_id,
            MappingDecision.user,
        ).filter(
            MappingDecision.cdm_name == cdm_name,
            MappingDecision.domain == domain,
            MappingDecision.action.in_(["approved", "modified"]),
        ).all()
        for sv, tid, user in all_users:
            key = (sv, tid)
            if user and user not in users_map.setdefault(key, []):
                users_map[key].append(user)

    source_vocab = _DOMAIN_TO_SOURCE_VOCAB.get(domain, "")

    # Lookup concept_code/class from CDM + drop codes already correctly in the CDM
    # (synced / same single target) — those need neither push nor re-export.
    concept_info: dict[int, dict] = {}
    redundant: set = set()
    target_ids = [d.target_concept_id for d in decisions if d.target_concept_id]
    if decisions:
        try:
            cdm_obj, conn = _get_cdm_conn(db, cdm_name)
            schema = _get_schema(db, cdm_obj)
            try:
                dialect = conn.dialect
                if target_ids:
                    id_frag, id_params = dialect.in_list("concept_id", target_ids)
                    with dialect.dict_cursor(conn) as cur:
                        dialect.execute(
                            cur,
                            f"SELECT concept_id, concept_code, concept_class_id "
                            f"FROM {schema.t('concept')} WHERE {id_frag}",
                            id_params,
                        )
                        for row in cur.fetchall():
                            concept_info[row["concept_id"]] = {
                                "concept_code": row["concept_code"],
                                "concept_class_id": row["concept_class_id"],
                            }
                if domain in DOMAIN_CONFIG:
                    cfg = get_domain_config(conn, schema, domain)
                    full_table = f"{schema.t(safe_identifier(cfg['table']))}"
                    sv_col = safe_identifier(cfg["source_value"])
                    concept_col = safe_identifier(cfg["concept_id"])
                    redundant = _redundant_svs_live(conn, full_table, sv_col, concept_col, decisions)
            finally:
                conn.close()
        except Exception:
            logger.warning("Failed export CDM lookups", exc_info=True)

    if redundant:
        decisions = [d for d in decisions if d.source_value not in redundant]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "sourceCode", "sourceName", "sourceFrequency", "sourceAutoAssignedConceptIds",
        "ADD_INFO:source_name_fr", "ADD_INFO:matchScore",
        "mappingStatus", "equivalence", "statusSetBy", "statusSetOn",
        "conceptId", "conceptName", "domainId", "mappingType", "comment",
        "createdBy", "createdOn", "assignedReviewers",
        "srce_vocabulary", "concept_code", "concept_name", "domain_id",
        "vocabulary_id", "concept_class_id", "standard_concept",
    ])
    for d in decisions:
        users = users_map.get((d.source_value, d.target_concept_id), [])
        users_str = ";".join(users) if users else (d.user or "")
        created_at = d.created_at.isoformat() if d.created_at else ""
        writer.writerow([
            csv_safe(d.source_value),
            csv_safe(d.source_name or d.source_value),
            freq_map.get(d.source_value, 0),
            d.previous_concept_id or 0,
            csv_safe(d.source_name or ""),
            d.confidence_score or "",
            "APPROVED",
            "EQUAL",
            csv_safe(users_str),
            created_at,
            d.target_concept_id or "",
            csv_safe(d.target_concept_name or ""),
            csv_safe(domain),
            "MAPS_TO",
            csv_safe(d.reason or ""),
            csv_safe(d.user or ""),
            created_at,
            "",
            csv_safe(source_vocab),
            csv_safe(concept_info.get(d.target_concept_id, {}).get("concept_code", "")),
            csv_safe(d.target_concept_name or ""),
            csv_safe(domain),
            csv_safe(d.target_vocabulary_id or ""),
            csv_safe(concept_info.get(d.target_concept_id, {}).get("concept_class_id", "")),
            "S",  # OPAL only maps to standard concepts
        ])
    output.seek(0)

    table_suffix = _DOMAIN_TO_TABLE.get(domain, domain.upper())
    filename = f"_{table_suffix}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ──── 5.6 History & Audit ────

def _status_decision_ids(db: Session, cdm_name: str, domain: str | None, status: str) -> list[int] | None:
    """Decision ids matching a *displayed* status (consensus-aware). Returns None for
    statuses that map directly onto the raw action column (rejected / rolled_back).

    Display rule: an approved/modified decision shows as 'pending' until 2+ distinct
    users approve the same (source_value → target); only then does it show as
    'approved' / 'modified'. So filtering must account for consensus, not the raw action.
    """
    if status not in ("pending", "approved", "modified"):
        return None
    from sqlalchemy import distinct
    cons_q = db.query(MappingDecision.source_value, MappingDecision.target_concept_id).filter(
        MappingDecision.cdm_name == cdm_name,
        MappingDecision.action.in_(["approved", "modified"]),
        MappingDecision.target_concept_id.isnot(None),
    )
    if domain:
        cons_q = cons_q.filter(MappingDecision.domain == domain)
    consensus = {
        (sv, tid) for sv, tid in
        cons_q.group_by(MappingDecision.source_value, MappingDecision.target_concept_id)
              .having(func.count(distinct(MappingDecision.user)) >= 2).all()
    }
    cand_q = db.query(
        MappingDecision.id, MappingDecision.source_value,
        MappingDecision.target_concept_id, MappingDecision.action,
    ).filter(
        MappingDecision.cdm_name == cdm_name,
        MappingDecision.action.in_(["approved", "modified"]),
    )
    if domain:
        cand_q = cand_q.filter(MappingDecision.domain == domain)
    ids: list[int] = []
    for cid, sv, tid, act in cand_q.all():
        cons = (sv, tid) in consensus
        if status == "pending" and not cons:
            ids.append(cid)
        elif status == "approved" and cons and act == "approved":
            ids.append(cid)
        elif status == "modified" and cons and act == "modified":
            ids.append(cid)
    return ids


def _apply_status_filter(query, db: Session, cdm_name: str, domain: str | None, status: str | None):
    """Filter a MappingDecision query by displayed status (consensus-aware)."""
    if not status:
        return query
    if status in ("rejected", "rolled_back"):
        return query.filter(MappingDecision.action == status)
    ids = _status_decision_ids(db, cdm_name, domain, status)
    if ids is not None:
        return query.filter(MappingDecision.id.in_(ids or [-1]))
    return query


@router.get("/history/{cdm_name}")
def mapping_history(
    cdm_name: str,
    domain: str | None = None,
    status: str | None = None,
    user_filter: str | None = Query(default=None, alias="user"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_by: str | None = Query(default=None),
    sort_dir: str = Query(default="asc"),
    hide_synced: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """Paginated mapping decision history with filters (shared across all users)."""
    query = db.query(MappingDecision).filter(MappingDecision.cdm_name == cdm_name)

    if domain:
        query = query.filter(MappingDecision.domain == domain)
    query = _apply_status_filter(query, db, cdm_name, domain, status)
    if user_filter:
        query = query.filter(MappingDecision.user == user_filter)
    if hide_synced:
        query = query.filter((MappingDecision.synced == 0) | (MappingDecision.synced.is_(None)))

    sort_columns = {
        "domain": MappingDecision.domain,
        "source": MappingDecision.source_name,
        "source_value": MappingDecision.source_value,
        "action": MappingDecision.action,
        "target": MappingDecision.target_concept_name,
        "confidence": MappingDecision.confidence_score,
        "reason": MappingDecision.reason,
        "user": MappingDecision.user,
        "date": MappingDecision.created_at,
    }
    sort_col = sort_columns.get(sort_by) if sort_by else None
    if sort_col is not None:
        ordering = desc(sort_col) if sort_dir.lower() == "desc" else sort_col
        query = query.order_by(ordering, MappingDecision.source_value, MappingDecision.domain)
    else:
        query = query.order_by(MappingDecision.source_value, MappingDecision.domain, desc(MappingDecision.created_at))

    total = query.count()
    offset = (page - 1) * page_size
    decisions = query.offset(offset).limit(page_size).all()

    # Distinct users for this CDM (for filter dropdown)
    distinct_users = [
        r[0] for r in
        db.query(MappingDecision.user)
        .filter(MappingDecision.cdm_name == cdm_name)
        .distinct().all()
    ]

    items = [
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
            "synced": bool(d.synced),
        }
        for d in decisions
    ]
    # CDM mapping state per (domain, source_value) → synced / different-target / 1→N badges
    _annotate_cdm_concept_counts(db, cdm_name, items)

    return {
        "total": total,
        "users": sorted(distinct_users),
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        "items": items,
    }


def _require_data_manager(request: Request) -> str:
    """Auth + role gate for synced marking (shared, cross-user history flag)."""
    username = _get_username(request)
    roles = getattr(request.state, "user", {}).get("roles", [])
    if "admin" not in roles and "data-manager" not in roles:
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs / data-managers")
    return username


@router.post("/decisions/mark-synced")
def mark_synced(req: SyncRequest, request: Request, db: Session = Depends(get_db)):
    """Mark as 'synced' the approved/modified decisions whose target is already the
    one (and only) concept mapped in the CDM (same concept). Reversible (unmark).
    Candidates are detected from the SourceValueCache — no live CDM query."""
    check_cdm_access(request, req.cdm_name)
    _require_data_manager(request)

    q = db.query(MappingDecision).filter(
        MappingDecision.cdm_name == req.cdm_name,
        MappingDecision.action.in_(["approved", "modified"]),
        MappingDecision.target_concept_id.isnot(None),
    )
    if req.domain:
        q = q.filter(MappingDecision.domain == req.domain)
    if req.source_values:
        q = q.filter(MappingDecision.source_value.in_(req.source_values))
    decisions = q.all()
    if not decisions:
        return {"marked": 0}

    pairs = {(d.domain, d.source_value) for d in decisions}
    ids_by = _cdm_concept_ids_by_sv(db, req.cdm_name, pairs)

    marked = 0
    for d in decisions:
        cids = ids_by.get((d.domain, d.source_value), [])
        # synced only when the CDM has exactly this one concept (no 1→N, no divergence)
        if len(cids) == 1 and cids[0] == d.target_concept_id and not d.synced:
            d.synced = 1
            marked += 1
    db.commit()
    return {"marked": marked}


@router.post("/decisions/unmark-synced")
def unmark_synced(req: SyncRequest, request: Request, db: Session = Depends(get_db)):
    """Reverse a previous sync marking (cdm + optional domain / source_values)."""
    check_cdm_access(request, req.cdm_name)
    _require_data_manager(request)

    q = db.query(MappingDecision).filter(
        MappingDecision.cdm_name == req.cdm_name,
        MappingDecision.synced == 1,
    )
    if req.domain:
        q = q.filter(MappingDecision.domain == req.domain)
    if req.source_values:
        q = q.filter(MappingDecision.source_value.in_(req.source_values))
    unmarked = q.update({MappingDecision.synced: 0}, synchronize_session=False)
    db.commit()
    return {"unmarked": int(unmarked or 0)}


@router.get("/history/{cdm_name}/export")
def export_mapping_history(
    cdm_name: str,
    domain: str | None = None,
    status: str | None = None,
    user_filter: str | None = Query(default=None, alias="user"),
    db: Session = Depends(get_db),
):
    """Export the mapping decision history as CSV (same filters as the history view)."""
    query = db.query(MappingDecision).filter(MappingDecision.cdm_name == cdm_name)
    if domain:
        query = query.filter(MappingDecision.domain == domain)
    query = _apply_status_filter(query, db, cdm_name, domain, status)
    if user_filter:
        query = query.filter(MappingDecision.user == user_filter)
    query = query.order_by(desc(MappingDecision.created_at))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "domain", "source_value", "source_name", "action",
        "target_concept_id", "target_concept_name", "target_vocabulary_id",
        "previous_concept_id", "suggestion_source", "confidence_score",
        "user", "reason", "created_at",
    ])
    for d in query.all():
        writer.writerow([
            csv_safe(d.domain or ""),
            csv_safe(d.source_value or ""),
            csv_safe(d.source_name or ""),
            csv_safe(d.action or ""),
            d.target_concept_id or "",
            csv_safe(d.target_concept_name or ""),
            csv_safe(d.target_vocabulary_id or ""),
            d.previous_concept_id or "",
            csv_safe(d.suggestion_source or ""),
            d.confidence_score if d.confidence_score is not None else "",
            csv_safe(d.user or ""),
            csv_safe(d.reason or ""),
            d.created_at.isoformat() if d.created_at else "",
        ])
    output.seek(0)
    filename = f"mapping_history_{cdm_name}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/history/{decision_id}/rollback")
def rollback_decision(decision_id: int, request: Request, db: Session = Depends(get_db)):
    """Rollback a specific mapping decision (own decisions only)."""
    username = _get_username(request)
    roles = getattr(request.state, "user", {}).get("roles", [])

    decision = db.query(MappingDecision).filter(MappingDecision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    # Only allow rollback of own decisions (admins can rollback any)
    if decision.user != username and "admin" not in roles:
        raise HTTPException(status_code=403, detail="Vous ne pouvez annuler que vos propres décisions")

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
        user=username,
    )
    db.add(rollback)

    # Remove the original decision
    db.delete(decision)
    db.commit()

    return {"rolled_back": True, "original_id": decision_id}


@router.post("/history/{decision_id}/withdraw")
def withdraw_decision(decision_id: int, request: Request, db: Session = Depends(get_db)):
    """Silently remove own decision (no rolled_back trace). Used to undo a consensus vote."""
    username = _get_username(request)
    roles = getattr(request.state, "user", {}).get("roles", [])

    decision = db.query(MappingDecision).filter(MappingDecision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    if decision.user != username and "admin" not in roles:
        raise HTTPException(status_code=403, detail="Vous ne pouvez retirer que vos propres décisions")

    db.delete(decision)
    db.commit()

    return {"withdrawn": True, "id": decision_id}


@router.post("/history/{decision_id}/reject")
def reject_decision(decision_id: int, request: Request, db: Session = Depends(get_db)):
    """Reject an existing mapping decision in-place (own decisions or admin)."""
    username = _get_username(request)
    roles = getattr(request.state, "user", {}).get("roles", [])

    decision = db.query(MappingDecision).filter(MappingDecision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    if decision.user != username and "admin" not in roles:
        raise HTTPException(status_code=403, detail="Vous ne pouvez rejeter que vos propres décisions")

    decision.action = "rejected"
    db.commit()

    return {"rejected": True, "id": decision_id}



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
