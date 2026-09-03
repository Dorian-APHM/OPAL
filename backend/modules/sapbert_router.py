"""
SapBERT feature API: the config flag, per-(cdm, domain) build state, and the
persistent per-domain suggestion toggle.

The heavy lifting (encoding/matching) happens at Source Value Cache build time
via the opal-sapbert service; these endpoints only expose the in-app state
(sapbert_domain_state) and let the user turn SapBERT suggestions on/off per
domain. The suggestion engine (mapping router) reads sapbert_mappings and honors
this toggle.
"""
import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from config import SAPBERT_ENABLED, SAPBERT_MODE
from db.app_db import get_db
from db.models import AnalysisSettings, CdmConfig, SapbertDomainState, SapbertMapping, SourceValueCache
from db.omop_connector import get_omop_connection
from utils.cdm_helper import build_schema_map, check_cdm_access
from utils.crypto import decrypt_password
from utils.thread_pool import submit_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sapbert", tags=["sapbert"])

# Standalone SapBERT builds in progress, keyed by cdm_name (separate from the
# Source Value Cache populate). Lets the UI show a spinner and block double runs.
_active_builds: dict[str, dict] = {}
_build_lock = threading.Lock()


@router.get("/config")
def get_config() -> dict:
    """Feature flag for the frontend. Always available (even when disabled)."""
    return {"enabled": SAPBERT_ENABLED, "mode": SAPBERT_MODE}


@router.get("/domains/{cdm_name}")
def list_domains(cdm_name: str, request: Request, db: Session = Depends(get_db)) -> dict:
    """Per-domain SapBERT build state + toggle for a CDM (only built domains appear)."""
    check_cdm_access(request, cdm_name)
    rows = (
        db.query(SapbertDomainState)
        .filter(SapbertDomainState.cdm_name == cdm_name)
        .order_by(SapbertDomainState.domain)
        .all()
    )
    with _build_lock:
        building = cdm_name in _active_builds
    # Actual mappings count per domain = source of truth for "is it built".
    counts = dict(
        db.query(SapbertMapping.domain, func.count(SapbertMapping.id))
        .filter(SapbertMapping.cdm_name == cdm_name)
        .group_by(SapbertMapping.domain)
        .all()
    )
    # When idle, self-heal the state from reality: a domain with mappings is
    # 'done' (even if a later rebuild was cancelled/errored without touching its
    # old data); a stale 'pending'/'running' with no data is 'cancelled'.
    if not building:
        changed = False
        for r in rows:
            actual = counts.get(r.domain, 0)
            if actual > 0 and r.status != "done":
                r.status, r.row_count, r.error_message, changed = "done", actual, None, True
            elif actual == 0 and r.status in ("pending", "running"):
                r.status, changed = "cancelled", True
        if changed:
            db.commit()
    return {
        "enabled": SAPBERT_ENABLED,
        "building": building,
        "domains": [
            {
                "domain": r.domain,
                "status": r.status,
                "row_count": counts.get(r.domain, r.row_count),
                "enabled": bool(r.enabled),
                "built_at": r.built_at.isoformat() if r.built_at else None,
                "error_message": r.error_message,
            }
            for r in rows
        ],
    }


class ToggleRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1, max_length=255)
    domain: str = Field(..., min_length=1, max_length=100)
    enabled: bool


@router.put("/toggle")
def toggle_domain(body: ToggleRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Enable/disable SapBERT suggestions for a (cdm, domain). Persisted across rebuilds."""
    check_cdm_access(request, body.cdm_name)
    state = (
        db.query(SapbertDomainState)
        .filter(
            SapbertDomainState.cdm_name == body.cdm_name,
            SapbertDomainState.domain == body.domain,
        )
        .first()
    )
    if state is None:
        raise HTTPException(404, f"SapBERT not built for {body.cdm_name}/{body.domain}")
    state.enabled = body.enabled
    db.commit()
    return {"cdm_name": body.cdm_name, "domain": body.domain, "enabled": bool(state.enabled)}


@router.get("/buildable/{cdm_name}")
def buildable_domains(cdm_name: str, request: Request, db: Session = Depends(get_db)) -> dict:
    """Domains with labelled cached source values — candidates for a SapBERT build."""
    check_cdm_access(request, cdm_name)
    rows = (
        db.query(
            SourceValueCache.domain,
            func.count(distinct(SourceValueCache.source_value)).label("n"),
        )
        .filter(
            SourceValueCache.cdm_name == cdm_name,
            SourceValueCache.source_name.isnot(None),
            SourceValueCache.source_name != "",
        )
        .group_by(SourceValueCache.domain)
        .order_by(func.count(distinct(SourceValueCache.source_value)).desc())
        .all()
    )
    return {"enabled": SAPBERT_ENABLED, "domains": [{"domain": d, "labelled": int(n)} for d, n in rows]}


@router.post("/build")
def build_sapbert(
    cdm_name: str,
    request: Request,
    domains: list[str] | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    """Build SapBERT mappings for the cached domains of a CDM, reusing the EXISTING
    Source Value Cache (no cache rebuild). Pass `domains` to restrict the build to a
    subset (e.g. exclude Drug). Runs in the background; poll GET /domains/{cdm} for
    per-domain progress and the `building` flag."""
    if not SAPBERT_ENABLED:
        raise HTTPException(503, "SapBERT is disabled (set SAPBERT_MODE=on)")
    check_cdm_access(request, cdm_name)

    with _build_lock:
        if cdm_name in _active_builds:
            return {"status": "already_running"}

    cdm = db.query(CdmConfig).filter(CdmConfig.name == cdm_name).first()
    if not cdm:
        raise HTTPException(404, "CDM not found")

    # Domains with labelled cached source values (only these can be embedded),
    # restricted to the requested subset.
    label_q = db.query(SourceValueCache.domain).filter(
        SourceValueCache.cdm_name == cdm_name,
        SourceValueCache.source_name.isnot(None),
        SourceValueCache.source_name != "",
    )
    if domains:
        label_q = label_q.filter(SourceValueCache.domain.in_(list(domains)))
    build_domains = [r[0] for r in label_q.distinct().all()]
    if not build_domains:
        raise HTTPException(400, "No labelled cached source values for the requested domains.")

    # Reset the selected domains to 'pending' (row_count 0) so the UI shows a
    # fresh build like the Source Value Cache, preserving each domain's toggle.
    for d in build_domains:
        st = (
            db.query(SapbertDomainState)
            .filter(SapbertDomainState.cdm_name == cdm_name, SapbertDomainState.domain == d)
            .first()
        )
        if st:
            st.status, st.row_count, st.error_message = "pending", 0, None
        else:
            db.add(SapbertDomainState(cdm_name=cdm_name, domain=d, status="pending", row_count=0))
    db.commit()

    password = decrypt_password(cdm.db_password_encrypted)
    settings = db.query(AnalysisSettings).filter(AnalysisSettings.cdm_name == cdm_name).first()
    schema = build_schema_map(cdm, settings)

    cancelled = {"v": False}
    with _build_lock:
        _active_builds[cdm_name] = {"cancelled": cancelled, "conn": None}

    def _worker():
        from modules.mapping.sapbert_build import build_domain_sapbert
        from modules.sapbert_client import SapbertCancelled
        try:
            conn = get_omop_connection(cdm.db_host, cdm.db_port, cdm.db_name, cdm.db_user, password, db_type=getattr(cdm, "db_type", None) or "postgresql")
            with _build_lock:
                if cdm_name in _active_builds:
                    _active_builds[cdm_name]["conn"] = conn
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = 0")
        except Exception:
            logger.exception("SapBERT build: cannot connect to CDM '%s'", cdm_name)
            with _build_lock:
                _active_builds.pop(cdm_name, None)
            return
        try:
            for domain in build_domains:
                if cancelled["v"]:
                    break
                try:
                    build_domain_sapbert(cdm_name, domain, conn, schema,
                                         cancel_check=lambda: cancelled["v"])
                except SapbertCancelled:
                    break  # stop the whole build
                except Exception:
                    logger.exception("SapBERT build failed for %s/%s", cdm_name, domain)
                    try:
                        conn.rollback()
                    except Exception:
                        pass
        finally:
            conn.close()
            with _build_lock:
                _active_builds.pop(cdm_name, None)

    submit_task(_worker)
    return {"status": "started", "domains": build_domains}


@router.post("/build/cancel")
def cancel_sapbert_build(cdm_name: str, request: Request) -> dict:
    """Cancel a running standalone SapBERT build (takes effect between domains)."""
    check_cdm_access(request, cdm_name)
    with _build_lock:
        task = _active_builds.get(cdm_name)
    if not task:
        raise HTTPException(404, "No active SapBERT build for this CDM")
    task["cancelled"]["v"] = True
    conn = task.get("conn")
    if conn:
        try:
            conn.cancel()
        except Exception:
            pass
    return {"status": "cancelling"}
