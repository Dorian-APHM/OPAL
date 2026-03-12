"""
Quality module API endpoints.
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

from db.app_db import get_db, SessionLocal
from db.models import CdmConfig, AnalysisSnapshot, AnalysisSettings
from utils.notifications import notify
from db.omop_connector import get_omop_connection
from utils.crypto import decrypt_password
from modules.quality.engine import get_available_domains, run_domain_analysis
from modules.quality.comparator import compare_snapshots
from config import DEFAULT_OMOP_SCHEMA

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/quality", tags=["quality"])

# Track active streaming analyses for cancel support.
# Key: analysis_id (str), Value: {"cancelled": bool, "conn": psycopg2 connection or None}
_active_analyses: dict[str, dict] = {}


class AnalysisRequest(BaseModel):
    cdm_name: str
    domain: str


class BatchAnalysisRequest(BaseModel):
    cdm_name: str
    domains: list[str]


class CompareRequest(BaseModel):
    cdm_name_a: str
    cdm_name_b: str
    domain: str
    snapshot_id_a: int | None = None
    snapshot_id_b: int | None = None


def _get_cdm_analysis_params(db: Session, cdm: CdmConfig) -> dict:
    """Helper to get analysis parameters for a CDM."""
    settings = db.query(AnalysisSettings).filter(
        AnalysisSettings.cdm_name == cdm.name
    ).first()
    return {
        "omop_schema": settings.omop_schema if settings else cdm.omop_schema or DEFAULT_OMOP_SCHEMA,
        "top_unmapped": settings.top_unmapped_terms if settings else 50,
        "top_concepts": settings.top_concepts if settings else 50,
        "max_rpp": settings.max_records_per_person if settings else 100,
        "max_obs": settings.max_observation_months if settings else 120,
    }


def _save_snapshot(db: Session, cdm_name: str, domain: str, results: dict) -> AnalysisSnapshot:
    """Save analysis results as a new versioned snapshot."""
    max_version = db.query(func.max(AnalysisSnapshot.version)).filter(
        AnalysisSnapshot.cdm_name == cdm_name,
        AnalysisSnapshot.domain == domain,
    ).scalar() or 0

    snapshot = AnalysisSnapshot(
        cdm_name=cdm_name,
        domain=domain,
        version=max_version + 1,
        results=results,
        created_at=datetime.utcnow(),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.get("/domains")
def list_domains():
    """List all available analysis domains."""
    return {"domains": get_available_domains()}


@router.post("/analyze")
def analyze_domain(req: AnalysisRequest, request: Request, db: Session = Depends(get_db)):
    """Run analysis for a single domain on a CDM."""
    cdm = db.query(CdmConfig).filter(CdmConfig.name == req.cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{req.cdm_name}' not found")

    available = get_available_domains()
    if req.domain not in available:
        raise HTTPException(status_code=400, detail=f"Unknown domain: {req.domain}")

    params = _get_cdm_analysis_params(db, cdm)
    password = decrypt_password(cdm.db_password_encrypted)
    try:
        conn = get_omop_connection(cdm.db_host, cdm.db_port, cdm.db_name, cdm.db_user, password)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cannot connect to CDM: {e}")

    try:
        results = run_domain_analysis(
            conn, req.domain,
            omop_schema=params["omop_schema"],
            top_unmapped=params["top_unmapped"],
            top_concepts=params["top_concepts"],
            max_records_per_person=params["max_rpp"],
            max_observation_months=params["max_obs"],
        )
    except Exception as e:
        logger.exception("Analysis failed for %s/%s", req.cdm_name, req.domain)
        raise HTTPException(status_code=500, detail=f"Analysis error: {e}")
    finally:
        conn.close()

    snapshot = _save_snapshot(db, req.cdm_name, req.domain, results)

    # Notify the user who launched the analysis
    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "")
    if username:
        notify(
            db, username, "quality_done",
            title=f"Analyse terminée : {req.domain}",
            message=f"L'analyse qualité de « {req.domain} » sur {req.cdm_name} est terminée.",
            link=f"/quality?cdm={req.cdm_name}&domain={req.domain}",
            item_id=req.domain,
        )
        db.commit()

    return {
        "snapshot_id": snapshot.id,
        "version": snapshot.version,
        "domain": req.domain,
        "cdm_name": req.cdm_name,
        "results": results,
    }


@router.post("/analyze/batch")
def analyze_batch(req: BatchAnalysisRequest, request: Request, db: Session = Depends(get_db)):
    """Run analysis for multiple domains on a CDM."""
    cdm = db.query(CdmConfig).filter(CdmConfig.name == req.cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{req.cdm_name}' not found")

    available = get_available_domains()
    invalid = [d for d in req.domains if d not in available]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unknown domains: {invalid}")

    params = _get_cdm_analysis_params(db, cdm)
    password = decrypt_password(cdm.db_password_encrypted)
    try:
        conn = get_omop_connection(cdm.db_host, cdm.db_port, cdm.db_name, cdm.db_user, password)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cannot connect to CDM: {e}")

    results_list = []
    errors = []
    try:
        for domain in req.domains:
            try:
                results = run_domain_analysis(
                    conn, domain, omop_schema=params["omop_schema"],
                    top_unmapped=params["top_unmapped"],
                    top_concepts=params["top_concepts"],
                    max_records_per_person=params["max_rpp"],
                    max_observation_months=params["max_obs"],
                )
                snapshot = _save_snapshot(db, req.cdm_name, domain, results)
                results_list.append({
                    "domain": domain,
                    "snapshot_id": snapshot.id,
                    "version": snapshot.version,
                    "status": "success",
                })
            except Exception as e:
                logger.exception("Batch analysis failed for %s/%s", req.cdm_name, domain)
                errors.append({"domain": domain, "error": str(e)})
    finally:
        conn.close()

    # Notify user
    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "")
    if username:
        domain_list = ", ".join(req.domains)
        for d in req.domains:
            notify(
                db, username, "quality_done",
                title=f"Analyse terminée : {d}",
                message=f"L'analyse qualité de « {d} » sur {req.cdm_name} est terminée.",
                link=f"/quality?cdm={req.cdm_name}&domain={d}",
                item_id=d,
            )
        db.commit()

    return {
        "cdm_name": req.cdm_name,
        "completed": results_list,
        "errors": errors,
        "total": len(req.domains),
        "success_count": len(results_list),
        "error_count": len(errors),
    }


@router.post("/analyze/batch/stream")
def analyze_batch_stream(req: BatchAnalysisRequest, request: Request, db: Session = Depends(get_db)):
    """Run batch analysis with SSE progress stream."""
    cdm = db.query(CdmConfig).filter(CdmConfig.name == req.cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{req.cdm_name}' not found")

    available = get_available_domains()
    invalid = [d for d in req.domains if d not in available]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unknown domains: {invalid}")

    params = _get_cdm_analysis_params(db, cdm)
    password = decrypt_password(cdm.db_password_encrypted)

    # Copy needed values before the generator (db session may close)
    cdm_host = cdm.db_host
    cdm_port = cdm.db_port
    cdm_dbname = cdm.db_name
    cdm_user = cdm.db_user
    cdm_name = req.cdm_name
    domains = list(req.domains)
    user = getattr(request.state, "user", {})
    trigger_username = user.get("preferred_username", "")

    # Register this analysis for cancel support
    import queue as _queue
    import threading as _threading
    import uuid as _uuid

    analysis_id = str(_uuid.uuid4())[:8]
    progress_q: _queue.Queue = _queue.Queue()

    def _worker():
        """Run the analysis in a background thread.

        Snapshots are saved per-domain and a notification is sent at the
        end.  The thread is completely independent of the SSE stream so
        the analysis survives client disconnects and page navigations.
        """
        _active_analyses[analysis_id] = {"cancelled": False, "conn": None, "cdm_name": cdm_name, "domains": domains, "completed": 0, "total": len(domains), "domain_status": []}

        try:
            conn = get_omop_connection(cdm_host, cdm_port, cdm_dbname, cdm_user, password)
        except Exception as e:
            progress_q.put({"type": "error", "message": str(e)})
            progress_q.put(None)  # sentinel
            _active_analyses.pop(analysis_id, None)
            return

        _active_analyses[analysis_id]["conn"] = conn
        total = len(domains)
        completed = 0
        cancelled = False
        succeeded_domains: list[str] = []

        try:
            for domain in domains:
                if _active_analyses.get(analysis_id, {}).get("cancelled"):
                    cancelled = True
                    progress_q.put({"type": "cancelled", "completed": completed, "total": total})
                    break

                progress_q.put({"type": "progress", "domain": domain, "status": "running",
                                "completed": completed, "total": total})
                try:
                    results = run_domain_analysis(
                        conn, domain, omop_schema=params["omop_schema"],
                        top_unmapped=params["top_unmapped"],
                        top_concepts=params["top_concepts"],
                        max_records_per_person=params["max_rpp"],
                        max_observation_months=params["max_obs"],
                    )
                    local_db = SessionLocal()
                    try:
                        _save_snapshot(local_db, cdm_name, domain, results)
                    finally:
                        local_db.close()

                    completed += 1
                    succeeded_domains.append(domain)
                    if analysis_id in _active_analyses:
                        _active_analyses[analysis_id]["completed"] = completed
                        _active_analyses[analysis_id]["domain_status"].append({"domain": domain, "status": "success"})
                    progress_q.put({"type": "progress", "domain": domain, "status": "success",
                                    "completed": completed, "total": total})
                except Exception as e:
                    completed += 1
                    if analysis_id in _active_analyses:
                        _active_analyses[analysis_id]["completed"] = completed
                        _active_analyses[analysis_id]["domain_status"].append({"domain": domain, "status": "error"})
                    progress_q.put({"type": "progress", "domain": domain, "status": "error",
                                    "error": str(e), "completed": completed, "total": total})
        finally:
            conn.close()
            _active_analyses.pop(analysis_id, None)

        if not cancelled and succeeded_domains:
            if trigger_username:
                notif_db = SessionLocal()
                try:
                    for d in succeeded_domains:
                        notify(
                            notif_db, trigger_username, "quality_done",
                            title=f"Analyse terminée : {d}",
                            message=f"L'analyse qualité de « {d} » sur {cdm_name} est terminée.",
                            link=f"/quality?cdm={cdm_name}&domain={d}",
                            item_id=d,
                        )
                    notif_db.commit()
                finally:
                    notif_db.close()
            progress_q.put({"type": "done", "completed": completed, "total": total})

        progress_q.put(None)  # sentinel — tells the SSE generator to stop

    # Start the worker thread — it runs independently of the HTTP connection.
    thread = _threading.Thread(target=_worker, daemon=True)
    thread.start()

    import asyncio as _asyncio

    async def event_generator():
        loop = _asyncio.get_event_loop()
        yield f"data: {json.dumps({'type': 'start', 'analysis_id': analysis_id, 'total': len(domains)})}\n\n"

        while True:
            # Read from the queue in a thread-safe, non-blocking way.
            try:
                event = await loop.run_in_executor(None, progress_q.get, True, 2.0)
            except _queue.Empty:
                continue
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/analyze/cancel/{analysis_id}")
def cancel_analysis(analysis_id: str):
    """Cancel a running streaming analysis.

    Sets the cancelled flag so the generator stops between domains.
    Also attempts to cancel the active PostgreSQL query.
    """
    entry = _active_analyses.get(analysis_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Analysis not found or already finished")

    entry["cancelled"] = True

    # Try to cancel the running PostgreSQL query
    conn = entry.get("conn")
    if conn and not conn.closed:
        try:
            conn.cancel()
            logger.info("Cancelled PostgreSQL query for analysis %s", analysis_id)
        except Exception as e:
            logger.warning("Failed to cancel query for %s: %s", analysis_id, e)

    return {"cancelled": True, "analysis_id": analysis_id}


@router.get("/analyze/active")
def list_active_analyses():
    """List currently running analyses (batch + conformity)."""
    return {
        "active": [
            {
                "analysis_id": aid,
                "cancelled": info.get("cancelled", False),
                "cdm_name": info.get("cdm_name", ""),
                "type": "conformity" if aid.startswith("conf-") else "batch",
                "domains": info.get("domains", []),
                "completed": info.get("completed", 0),
                "total": info.get("total", 0),
                "domain_status": info.get("domain_status", []),
            }
            for aid, info in _active_analyses.items()
        ]
    }


@router.post("/conformity")
def run_conformity(req: AnalysisRequest, request: Request, db: Session = Depends(get_db)):
    """Run CDM conformity validation checks in a background thread.

    Returns immediately with an analysis_id.  The result is persisted as
    an AnalysisSnapshot with domain='Conformity' so it survives page
    navigation.  Supports cancel via /conformity/cancel/{analysis_id}.
    """
    import threading as _threading
    import uuid as _uuid

    cdm = db.query(CdmConfig).filter(CdmConfig.name == req.cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{req.cdm_name}' not found")

    params = _get_cdm_analysis_params(db, cdm)
    password = decrypt_password(cdm.db_password_encrypted)

    # Copy values before the thread starts (db session may close).
    cdm_host, cdm_port, cdm_dbname, cdm_user = cdm.db_host, cdm.db_port, cdm.db_name, cdm.db_user
    cdm_name = req.cdm_name
    omop_schema = params["omop_schema"]
    user = getattr(request.state, "user", {})
    trigger_username = user.get("preferred_username", "")

    analysis_id = f"conf-{_uuid.uuid4().hex[:8]}"
    _active_analyses[analysis_id] = {"cancelled": False, "conn": None, "cdm_name": cdm_name, "domains": ["Conformity"]}

    def _worker():
        from modules.quality.conformity import run_conformity_checks

        try:
            conn = get_omop_connection(cdm_host, cdm_port, cdm_dbname, cdm_user, password)
        except Exception as e:
            logger.error("Conformity: cannot connect to CDM %s: %s", cdm_name, e)
            _active_analyses.pop(analysis_id, None)
            return

        _active_analyses[analysis_id]["conn"] = conn

        try:
            if _active_analyses.get(analysis_id, {}).get("cancelled"):
                return

            report = run_conformity_checks(conn, omop_schema=omop_schema)

            if _active_analyses.get(analysis_id, {}).get("cancelled"):
                return

            # Persist result as a snapshot with domain='Conformity'
            local_db = SessionLocal()
            try:
                _save_snapshot(local_db, cdm_name, "Conformity", report)
                if trigger_username:
                    notify(
                        local_db, trigger_username, "quality_done",
                        title=f"Conformité terminée — {cdm_name}",
                        message=f"Score : {report.get('score', '?')}/100",
                        link=f"/quality?cdm={cdm_name}",
                        item_id="Conformity",
                    )
                    local_db.commit()
            finally:
                local_db.close()

        except Exception as e:
            if not _active_analyses.get(analysis_id, {}).get("cancelled"):
                logger.exception("Conformity check failed for %s", cdm_name)
        finally:
            conn.close()
            _active_analyses.pop(analysis_id, None)

    thread = _threading.Thread(target=_worker, daemon=True)
    thread.start()

    return {"cdm_name": cdm_name, "analysis_id": analysis_id, "status": "started"}


@router.post("/conformity/cancel/{analysis_id}")
def cancel_conformity(analysis_id: str):
    """Cancel a running conformity check."""
    entry = _active_analyses.get(analysis_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Analysis not found or already finished")
    entry["cancelled"] = True
    conn = entry.get("conn")
    if conn and not conn.closed:
        try:
            conn.cancel()
        except Exception as e:
            logger.warning("Failed to cancel conformity query %s: %s", analysis_id, e)
    return {"cancelled": True, "analysis_id": analysis_id}


@router.get("/conformity/{cdm_name}")
def get_conformity(cdm_name: str, db: Session = Depends(get_db)):
    """Get the latest conformity result for a CDM (from snapshots)."""
    snapshot = (
        db.query(AnalysisSnapshot)
        .filter(AnalysisSnapshot.cdm_name == cdm_name, AnalysisSnapshot.domain == "Conformity")
        .order_by(AnalysisSnapshot.version.desc())
        .first()
    )
    if not snapshot:
        return {"cdm_name": cdm_name, "result": None}
    return {
        "cdm_name": cdm_name,
        "snapshot_id": snapshot.id,
        "version": snapshot.version,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "result": snapshot.results,
    }


@router.get("/snapshots/{cdm_name}/{domain}")
def list_snapshots(cdm_name: str, domain: str, db: Session = Depends(get_db)):
    """List all snapshots for a CDM/domain pair."""
    snapshots = (
        db.query(AnalysisSnapshot)
        .filter(AnalysisSnapshot.cdm_name == cdm_name, AnalysisSnapshot.domain == domain)
        .order_by(AnalysisSnapshot.version.desc())
        .all()
    )
    return {
        "cdm_name": cdm_name,
        "domain": domain,
        "snapshots": [
            {
                "id": s.id,
                "version": s.version,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in snapshots
        ],
    }


@router.get("/snapshots/{cdm_name}/{domain}/latest")
def get_latest_snapshot(cdm_name: str, domain: str, db: Session = Depends(get_db)):
    """Get the latest analysis snapshot for a CDM/domain."""
    snapshot = (
        db.query(AnalysisSnapshot)
        .filter(AnalysisSnapshot.cdm_name == cdm_name, AnalysisSnapshot.domain == domain)
        .order_by(AnalysisSnapshot.version.desc())
        .first()
    )
    if not snapshot:
        raise HTTPException(status_code=404, detail="No snapshots found")
    return {
        "id": snapshot.id,
        "version": snapshot.version,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "results": snapshot.results,
    }


@router.get("/snapshots/by-id/{snapshot_id}")
def get_snapshot_by_id(snapshot_id: int, db: Session = Depends(get_db)):
    """Get a specific snapshot by ID."""
    snapshot = db.query(AnalysisSnapshot).filter(AnalysisSnapshot.id == snapshot_id).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {
        "id": snapshot.id,
        "cdm_name": snapshot.cdm_name,
        "domain": snapshot.domain,
        "version": snapshot.version,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "results": snapshot.results,
    }


@router.get("/export/{snapshot_id}/{table_type}")
def export_csv(snapshot_id: int, table_type: str, db: Session = Depends(get_db)):
    """
    Export a table from a snapshot as CSV.
    table_type: top_concepts, top_unmapped, domain_stats, mapping_stats,
                gender, birth_year, age_by_gender, duration_by_gender
    """
    snapshot = db.query(AnalysisSnapshot).filter(AnalysisSnapshot.id == snapshot_id).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    results = snapshot.results
    output = io.StringIO()
    writer = csv.writer(output)
    filename = f"{snapshot.cdm_name}_{snapshot.domain}_v{snapshot.version}_{table_type}.csv"

    if table_type == "top_concepts":
        concepts = results.get("achilles_like", {}).get("top_concepts", [])
        writer.writerow(["concept_id", "concept_name", "source_value", "n_records", "n_persons"])
        for c in concepts:
            writer.writerow([c["concept_id"], c["concept_name"], c["source_value"], c["n_records"], c["n_persons"]])

    elif table_type == "top_unmapped":
        unmapped = results.get("mapping", {}).get("top_unmapped_terms", [])
        has_name = any("source_name" in u for u in unmapped)
        header = ["source_value"]
        if has_name:
            header.append("source_name")
        header.append("count")
        writer.writerow(header)
        for u in unmapped:
            row = [u["source_value"]]
            if has_name:
                row.append(u.get("source_name", ""))
            row.append(u["count"])
            writer.writerow(row)

    elif table_type == "domain_stats":
        domains = results.get("summary", {}).get("domains", [])
        writer.writerow(["domain", "total_records", "distinct_persons", "pct_persons",
                         "total_terms", "mapped_terms", "unmapped_terms", "pct_terms_mapped"])
        for d in domains:
            writer.writerow([d["domain"], d["total_records"], d["distinct_persons"],
                             d["pct_persons"], d["total_terms"], d["mapped_terms"],
                             d["unmapped_terms"], d["pct_terms_mapped"]])

    elif table_type == "age_by_gender":
        rows = results.get("achilles_like", {}).get("age_by_gender", {}).get("rows", [])
        writer.writerow(["gender_name", "n", "mean_age", "p10", "p25", "median_age", "p75", "p90"])
        for r in rows:
            writer.writerow([r["gender_name"], r["n"], r.get("mean_age"), r["p10"], r["p25"],
                             r.get("median_age"), r["p75"], r["p90"]])

    elif table_type == "duration_by_gender":
        rows = results.get("achilles_like", {}).get("duration_by_gender", {}).get("rows", [])
        writer.writerow(["gender_name", "n", "mean_months", "p10", "p25", "median_months", "p75", "p90"])
        for r in rows:
            writer.writerow([r["gender_name"], r["n"], r.get("mean_months"), r["p10"], r["p25"],
                             r.get("median_months"), r["p75"], r["p90"]])

    else:
        raise HTTPException(status_code=400, detail=f"Unknown table type: {table_type}")

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/timeline/{cdm_name}")
def get_timeline(
    cdm_name: str,
    domain: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Return KPI evolution across all snapshots for a CDM.
    If domain is specified, returns timeline for that domain only.
    Otherwise returns a summary across all domains.
    """
    query = (
        db.query(AnalysisSnapshot)
        .filter(AnalysisSnapshot.cdm_name == cdm_name)
    )
    if domain:
        query = query.filter(AnalysisSnapshot.domain == domain)

    snapshots = query.order_by(AnalysisSnapshot.domain, AnalysisSnapshot.version).all()

    if not snapshots:
        return {"cdm_name": cdm_name, "timelines": {}}

    timelines: dict[str, list] = {}
    for s in snapshots:
        d = s.domain
        if d not in timelines:
            timelines[d] = []
        point = _extract_kpis(s)
        timelines[d].append(point)

    return {"cdm_name": cdm_name, "timelines": timelines}


def _extract_kpis(snapshot: AnalysisSnapshot) -> dict:
    """Extract key KPIs from a snapshot for timeline display."""
    r = snapshot.results or {}
    point = {
        "snapshot_id": snapshot.id,
        "version": snapshot.version,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
    }

    domain = r.get("domain", snapshot.domain)

    if domain == "Dashboard":
        summary = r.get("summary", {})
        point["total_persons"] = summary.get("total_persons")
        domains_list = summary.get("domains", [])
        total_records = sum(d.get("total_records", 0) for d in domains_list)
        avg_mapping = None
        mapping_vals = [d.get("pct_terms_mapped") for d in domains_list if d.get("pct_terms_mapped") is not None]
        if mapping_vals:
            avg_mapping = round(sum(mapping_vals) / len(mapping_vals), 1)
        point["total_records"] = total_records
        point["avg_pct_terms_mapped"] = avg_mapping

    elif domain == "Person":
        ps = r.get("achilles_like", {}).get("person_summary", {})
        point["total_persons"] = ps.get("total_persons")

    elif domain == "ObservationPeriod":
        pass

    else:
        g = r.get("achilles_like", {}).get("global", {})
        point["total_records"] = g.get("total_rows")
        point["distinct_persons"] = g.get("distinct_persons")
        mt = r.get("mapping", {}).get("terms", {})
        point["pct_terms_mapped"] = mt.get("pct_terms_mapped")
        mr = r.get("mapping", {}).get("rows", {})
        point["pct_rows_mapped"] = mr.get("pct_rows_mapped")

    return point


@router.get("/report/comparison")
def generate_comparison_report(
    cdm_name_a: str,
    cdm_name_b: str,
    domain: str | None = Query(default=None),
    lang: str = Query(default="en"),
    db: Session = Depends(get_db),
):
    """Generate an HTML comparison report between two CDMs for one or all domains."""
    from modules.quality.report_builder import build_comparison_html_report

    target_domains = [domain] if domain else get_available_domains()

    # Get threshold from CDM A settings
    settings = db.query(AnalysisSettings).filter(AnalysisSettings.cdm_name == cdm_name_a).first()
    threshold = settings.comparison_alert_threshold if settings else 5.0

    comparisons = []
    for dom in target_domains:
        snap_a = (
            db.query(AnalysisSnapshot)
            .filter(AnalysisSnapshot.cdm_name == cdm_name_a, AnalysisSnapshot.domain == dom)
            .order_by(AnalysisSnapshot.version.desc())
            .first()
        )
        snap_b = (
            db.query(AnalysisSnapshot)
            .filter(AnalysisSnapshot.cdm_name == cdm_name_b, AnalysisSnapshot.domain == dom)
            .order_by(AnalysisSnapshot.version.desc())
            .first()
        )
        if snap_a and snap_b:
            comp = compare_snapshots(snap_a.results, snap_b.results, threshold=threshold)
            comparisons.append({
                "domain": comp["domain"],
                "diffs": comp["diffs"],
                "alerts": comp["alerts"],
                "threshold": comp["threshold"],
                "snap_a": {"id": snap_a.id, "cdm_name": snap_a.cdm_name, "version": snap_a.version},
                "snap_b": {"id": snap_b.id, "cdm_name": snap_b.cdm_name, "version": snap_b.version},
                "results_a": snap_a.results,
                "results_b": snap_b.results,
            })

    if not comparisons:
        raise HTTPException(status_code=404, detail="No common snapshots found between the two CDMs")

    html = build_comparison_html_report(cdm_name_a, cdm_name_b, comparisons, lang=lang)

    suffix = f"_{domain}" if domain else ""
    return StreamingResponse(
        iter([html]),
        media_type="text/html",
        headers={"Content-Disposition": f"attachment; filename=opal_comparison_{cdm_name_a}_vs_{cdm_name_b}{suffix}.html"},
    )


@router.get("/report/{cdm_name}")
def generate_report(
    cdm_name: str,
    lang: str = Query(default="en"),
    db: Session = Depends(get_db),
):
    """Generate an HTML quality report for a CDM (latest snapshots for all domains)."""
    from modules.quality.report_builder import build_html_report

    all_domains = get_available_domains()
    snapshots_data = {}
    for dom in all_domains:
        snap = (
            db.query(AnalysisSnapshot)
            .filter(AnalysisSnapshot.cdm_name == cdm_name, AnalysisSnapshot.domain == dom)
            .order_by(AnalysisSnapshot.version.desc())
            .first()
        )
        if snap:
            snapshots_data[dom] = {
                "version": snap.version,
                "created_at": snap.created_at.isoformat() if snap.created_at else None,
                "results": snap.results,
            }

    if not snapshots_data:
        raise HTTPException(status_code=404, detail="No snapshots found for this CDM")

    html = build_html_report(cdm_name, snapshots_data, lang=lang)

    return StreamingResponse(
        iter([html]),
        media_type="text/html",
        headers={"Content-Disposition": f"attachment; filename=opal_report_{cdm_name}.html"},
    )


@router.post("/compare")
def compare_cdms(req: CompareRequest, db: Session = Depends(get_db)):
    """Compare analysis results between two CDMs or two snapshots."""
    # Get snapshot A
    if req.snapshot_id_a:
        snap_a = db.query(AnalysisSnapshot).filter(AnalysisSnapshot.id == req.snapshot_id_a).first()
    else:
        snap_a = (
            db.query(AnalysisSnapshot)
            .filter(AnalysisSnapshot.cdm_name == req.cdm_name_a, AnalysisSnapshot.domain == req.domain)
            .order_by(AnalysisSnapshot.version.desc())
            .first()
        )
    if not snap_a:
        raise HTTPException(status_code=404, detail=f"No snapshot found for {req.cdm_name_a}/{req.domain}")

    # Get snapshot B
    if req.snapshot_id_b:
        snap_b = db.query(AnalysisSnapshot).filter(AnalysisSnapshot.id == req.snapshot_id_b).first()
    else:
        snap_b = (
            db.query(AnalysisSnapshot)
            .filter(AnalysisSnapshot.cdm_name == req.cdm_name_b, AnalysisSnapshot.domain == req.domain)
            .order_by(AnalysisSnapshot.version.desc())
            .first()
        )
    if not snap_b:
        raise HTTPException(status_code=404, detail=f"No snapshot found for {req.cdm_name_b}/{req.domain}")

    # Get threshold from settings
    settings = db.query(AnalysisSettings).filter(AnalysisSettings.cdm_name == req.cdm_name_a).first()
    threshold = settings.comparison_alert_threshold if settings else 5.0

    comparison = compare_snapshots(snap_a.results, snap_b.results, threshold=threshold)
    comparison["snapshot_a"] = {"id": snap_a.id, "cdm_name": snap_a.cdm_name, "version": snap_a.version}
    comparison["snapshot_b"] = {"id": snap_b.id, "cdm_name": snap_b.cdm_name, "version": snap_b.version}
    comparison["results_a"] = snap_a.results
    comparison["results_b"] = snap_b.results

    return comparison
