"""
Data Management module API endpoints.

Allows users to select a saved cohort, pick OMOP tables/columns,
and extract a flat dataset for research use.

Extraction runs as a background task with progress polling (same pattern
as cohort characterization / quality analysis).
"""
import csv
import io
import logging
import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func
from psycopg2.extras import DictCursor

from db.app_db import get_db, SessionLocal
from db.models import CdmConfig, Cohort, CohortVersion, AnalysisSettings
from db.omop_connector import get_omop_connection
from utils.crypto import decrypt_password
from utils.notifications import notify
from config import DEFAULT_OMOP_SCHEMA
from modules.cohort.sql_builder import build_cohort_sql
from modules.datamanagement.extractor import (
    list_available_tables,
    get_table_columns,
    build_extraction_sql,
    EXTRACTABLE_TABLES,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/datamanagement", tags=["datamanagement"])


# ──── Helpers ────

def _get_omop_schema(db: Session, cdm: CdmConfig) -> str:
    settings = db.query(AnalysisSettings).filter(
        AnalysisSettings.cdm_name == cdm.name
    ).first()
    return settings.omop_schema if settings else cdm.omop_schema or DEFAULT_OMOP_SCHEMA


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


def _get_cdm_conn_raw(db: Session, cdm_name: str):
    """Like _get_cdm_conn but raises ValueError instead of HTTPException (for threads)."""
    cdm = db.query(CdmConfig).filter(CdmConfig.name == cdm_name).first()
    if not cdm:
        raise ValueError(f"CDM '{cdm_name}' not found")
    password = decrypt_password(cdm.db_password_encrypted)
    conn = get_omop_connection(cdm.db_host, cdm.db_port, cdm.db_name, cdm.db_user, password)
    return cdm, conn


def _get_cohort_and_version(db: Session, cohort_id: int):
    """Get cohort and its latest version."""
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
    return cohort, version


def _cohort_has_same_visit(criteria: dict) -> bool:
    """Check if cohort criteria has sameVisit enabled on inclusion group."""
    inclusion = criteria.get("inclusion", {})
    return bool(inclusion.get("sameVisit", False))


# ──── Request Models ────

class TableSelection(BaseModel):
    table: str = Field(..., min_length=1)
    columns: list[str] = Field(..., min_length=1)


class ExtractRequest(BaseModel):
    cohort_id: int
    same_visit_only: bool = False
    table_selections: list[TableSelection] = Field(..., min_length=1)
    preview_limit: int = Field(default=50, ge=1, le=1000)


# ──── Background task registry ────
_active_extractions: dict[str, dict] = {}
_extractions_lock = threading.Lock()
_MAX_ACTIVE_EXTRACTIONS = 100


# ──── Endpoints ────

@router.get("/cohorts")
def list_cohorts_for_extraction(
    cdm_name: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    """List saved cohorts available for data extraction."""
    # Subquery: get the max version per cohort_id
    max_ver_subq = (
        db.query(
            CohortVersion.cohort_id,
            func.max(CohortVersion.version).label("max_version"),
        )
        .group_by(CohortVersion.cohort_id)
        .subquery()
    )
    # Join cohorts with their latest version in a single query
    rows = (
        db.query(Cohort, CohortVersion)
        .outerjoin(max_ver_subq, Cohort.id == max_ver_subq.c.cohort_id)
        .outerjoin(
            CohortVersion,
            (CohortVersion.cohort_id == Cohort.id)
            & (CohortVersion.version == max_ver_subq.c.max_version),
        )
        .filter(Cohort.cdm_name == cdm_name)
        .order_by(Cohort.updated_at.desc())
        .all()
    )
    result = []
    for c, latest in rows:
        has_same_visit = False
        if latest and latest.criteria_json:
            has_same_visit = _cohort_has_same_visit(latest.criteria_json)
        result.append({
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "cdm_name": c.cdm_name,
            "patient_count": latest.patient_count if latest else None,
            "latest_version": latest.version if latest else None,
            "has_same_visit": has_same_visit,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        })
    return {"cohorts": result}


@router.get("/tables")
def list_tables(
    cdm_name: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    """List available OMOP tables for extraction."""
    cdm, conn = _get_cdm_conn(db, cdm_name)
    schema = _get_omop_schema(db, cdm)
    try:
        tables = list_available_tables(conn, schema)
        result = []
        for t in tables:
            meta = EXTRACTABLE_TABLES.get(t, {})
            result.append({
                "table_name": t,
                "has_visit": meta.get("has_visit", False),
            })
        return {"tables": result}
    finally:
        conn.close()


@router.get("/tables/{table_name}/columns")
def list_columns(
    table_name: str,
    cdm_name: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    """List columns for a given OMOP table."""
    cdm, conn = _get_cdm_conn(db, cdm_name)
    schema = _get_omop_schema(db, cdm)
    try:
        columns = get_table_columns(conn, schema, table_name)
        return {"table": table_name, "columns": columns}
    finally:
        conn.close()


# ──── Background extraction (preview + download) ────

def _build_extraction_context(db: Session, req: ExtractRequest):
    """Validate request and return (cohort, cdm, conn, schema, extraction_sql, cohort_has_visit)."""
    cohort, version = _get_cohort_and_version(db, req.cohort_id)
    cdm, conn = _get_cdm_conn(db, cohort.cdm_name)
    schema = _get_omop_schema(db, cdm)

    criteria = version.criteria_json
    cohort_has_visit = _cohort_has_same_visit(criteria)

    if req.same_visit_only and not cohort_has_visit:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Cannot use 'Same Visit Only' mode: this cohort was not built with sameVisit enabled.",
        )

    include_visit_id = cohort_has_visit
    cohort_sql = build_cohort_sql(criteria, schema, include_visit_id=include_visit_id)

    table_sels = [{"table": s.table, "columns": s.columns} for s in req.table_selections]
    extraction_sql = build_extraction_sql(
        cohort_sql=cohort_sql,
        omop_schema=schema,
        table_selections=table_sels,
        same_visit_only=req.same_visit_only,
        cohort_has_visit=cohort_has_visit,
    )
    return cohort, cdm, conn, schema, extraction_sql


@router.post("/extract/start")
def extract_start(req: ExtractRequest, request: Request, db: Session = Depends(get_db)):
    """
    Launch extraction as a background task.
    Returns a task_id for polling via /extract/status/{task_id}.

    The task performs:
    1. Count total rows
    2. Execute preview (limited rows)
    3. Build full CSV in memory

    Progress is reported at each step.
    """
    # Validate upfront (will raise HTTPException if invalid)
    cohort, version = _get_cohort_and_version(db, req.cohort_id)
    cdm_name = cohort.cdm_name
    cohort_name = cohort.name

    criteria = version.criteria_json
    cohort_has_visit = _cohort_has_same_visit(criteria)

    if req.same_visit_only and not cohort_has_visit:
        raise HTTPException(
            status_code=400,
            detail="Cannot use 'Same Visit Only' mode: this cohort was not built with sameVisit enabled.",
        )

    # Capture request user for notifications
    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "anonymous")

    task_id = str(uuid.uuid4())
    with _extractions_lock:
        # Evict completed/error tasks if at capacity
        if len(_active_extractions) >= _MAX_ACTIVE_EXTRACTIONS:
            stale = [k for k, v in _active_extractions.items() if v["status"] in ("completed", "error")]
            for k in stale:
                del _active_extractions[k]
        if len(_active_extractions) >= _MAX_ACTIVE_EXTRACTIONS:
            raise HTTPException(status_code=429, detail="Too many concurrent extractions")
        _active_extractions[task_id] = {
            "status": "running",
            "cdm_name": cdm_name,
            "cohort_name": cohort_name,
            "cohort_id": req.cohort_id,
            "username": username,
            "completed": 0,
            "total": 3,  # count + preview + full CSV
            "current_step": "",
            "result": None,
            "csv_data": None,
            "csv_filename": None,
            "error": None,
        }

    # Serialise request params for the thread
    cohort_id = req.cohort_id
    same_visit_only = req.same_visit_only
    table_sels_raw = [{"table": s.table, "columns": s.columns} for s in req.table_selections]
    preview_limit = req.preview_limit

    def _progress(completed: int, total: int, step_label: str):
        with _extractions_lock:
            task = _active_extractions.get(task_id)
            if task:
                task["completed"] = completed
                task["total"] = total
                task["current_step"] = step_label

    def _worker():
        conn = None
        try:
            # Open own DB session + CDM connection in thread
            thread_db = SessionLocal()
            try:
                cohort_t, version_t = _get_cohort_and_version(thread_db, cohort_id)
                cdm_t, conn = _get_cdm_conn_raw(thread_db, cdm_name)
                schema = _get_omop_schema(thread_db, cdm_t)
            finally:
                thread_db.close()

            criteria_t = version_t.criteria_json
            ch_visit = _cohort_has_same_visit(criteria_t)
            include_visit_id = ch_visit
            cohort_sql = build_cohort_sql(criteria_t, schema, include_visit_id=include_visit_id)

            extraction_sql = build_extraction_sql(
                cohort_sql=cohort_sql,
                omop_schema=schema,
                table_selections=table_sels_raw,
                same_visit_only=same_visit_only,
                cohort_has_visit=ch_visit,
            )

            # Step 1: Count total rows
            _progress(0, 3, "Counting rows...")
            count_sql = f"SELECT COUNT(*) FROM ({extraction_sql}) _cnt"
            with conn.cursor() as cur:
                cur.execute(count_sql)
                total_count = cur.fetchone()[0]
            _progress(1, 3, "Counting rows")

            # Step 2: Preview (limited rows)
            _progress(1, 3, "Fetching preview...")
            limited_sql = f"{extraction_sql}\nLIMIT {preview_limit}"
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(limited_sql)
                columns = [desc[0] for desc in cur.description] if cur.description else []
                rows = [dict(r) for r in cur.fetchall()]
                # Serialise non-JSON types
                for row in rows:
                    for k, v in row.items():
                        if hasattr(v, 'isoformat'):
                            row[k] = v.isoformat()
                        elif isinstance(v, (bytes, memoryview)):
                            row[k] = str(v)
            _progress(2, 3, "Fetching preview")

            # Step 3: Build full CSV
            _progress(2, 3, "Building CSV...")
            csv_buf = io.StringIO()
            writer = csv.writer(csv_buf)
            with conn.cursor(name="extract_cursor", cursor_factory=DictCursor) as cur:
                cur.itersize = 2000
                cur.execute(extraction_sql)
                # Named cursors: description is None until first fetch
                first_row = cur.fetchone()
                csv_columns = [desc[0] for desc in cur.description] if cur.description else []
                writer.writerow(csv_columns)
                if first_row:
                    writer.writerow([
                        v.isoformat() if hasattr(v, 'isoformat') else v
                        for v in (first_row[col] for col in csv_columns)
                    ])
                for row in cur:
                    writer.writerow([
                        v.isoformat() if hasattr(v, 'isoformat') else v
                        for v in (row[col] for col in csv_columns)
                    ])
            _progress(3, 3, "Done")

            filename = f"dataset_{cohort_name.replace(' ', '_')}_{cohort_id}.csv"

            with _extractions_lock:
                task = _active_extractions.get(task_id)
                if task:
                    task["result"] = {
                        "columns": columns,
                        "rows": rows,
                        "total_count": total_count,
                        "preview_limit": preview_limit,
                        "cohort_name": cohort_name,
                        "sql": extraction_sql,
                    }
                    task["csv_data"] = csv_buf.getvalue()
                    task["csv_filename"] = filename
                    task["status"] = "completed"

            # Send notification
            try:
                notif_db = SessionLocal()
                try:
                    notify(
                        notif_db,
                        username=username,
                        notif_type="extraction_done",
                        title=f"Extraction ready: {cohort_name}",
                        message=f"{total_count} rows extracted from cohort '{cohort_name}'",
                        link="/data-management",
                        item_id=task_id,
                    )
                    notif_db.commit()
                finally:
                    notif_db.close()
            except Exception:
                logger.warning("Failed to create extraction notification", exc_info=True)

        except Exception as e:
            logger.exception("Extraction failed")
            with _extractions_lock:
                task = _active_extractions.get(task_id)
                if task:
                    task["error"] = "An internal error occurred during data extraction"
                    task["status"] = "error"
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    return {"task_id": task_id, "status": "running"}


@router.get("/extract/status/{task_id}")
def extract_status(task_id: str):
    """Poll the status of an extraction task."""
    with _extractions_lock:
        task = _active_extractions.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    resp: dict = {
        "task_id": task_id,
        "status": task["status"],
        "completed": task.get("completed", 0),
        "total": task.get("total", 3),
        "current_step": task.get("current_step", ""),
        "cohort_name": task.get("cohort_name", ""),
    }
    if task["status"] == "completed":
        resp["result"] = task["result"]
        # Don't clean up yet — CSV may still be downloaded
    elif task["status"] == "error":
        resp["error"] = task["error"]
        with _extractions_lock:
            _active_extractions.pop(task_id, None)
    return resp


@router.get("/extract/download/{task_id}")
def extract_download_task(task_id: str):
    """Download the CSV produced by a completed extraction task."""
    with _extractions_lock:
        task = _active_extractions.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="Extraction not yet completed")

    csv_data = task.get("csv_data")
    filename = task.get("csv_filename", "dataset.csv")
    if not csv_data:
        raise HTTPException(status_code=404, detail="CSV data not available")

    # Clean up after download — free memory
    # Use a copy so cleanup doesn't race with the streaming response
    with _extractions_lock:
        _active_extractions.pop(task_id, None)

    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(csv_data.encode("utf-8"))),
        },
    )


@router.post("/extract/cancel/{task_id}")
def extract_cancel(task_id: str):
    """Cancel/clean up an extraction task."""
    with _extractions_lock:
        task = _active_extractions.pop(task_id, None)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "cancelled"}


@router.get("/extract/active")
def extract_active():
    """Return any currently running extraction task."""
    with _extractions_lock:
        items = list(_active_extractions.items())
    for tid, task in items:
        if task["status"] == "running":
            return {
                "task_id": tid,
                "status": "running",
                "cdm_name": task.get("cdm_name"),
                "cohort_name": task.get("cohort_name"),
                "completed": task.get("completed", 0),
                "total": task.get("total", 3),
                "current_step": task.get("current_step", ""),
            }
    # Also return completed tasks not yet downloaded
    for tid, task in items:
        if task["status"] == "completed":
            return {
                "task_id": tid,
                "status": "completed",
                "cdm_name": task.get("cdm_name"),
                "cohort_name": task.get("cohort_name"),
                "completed": task.get("total", 3),
                "total": task.get("total", 3),
                "current_step": "Done",
            }
    return {"task_id": None, "status": "none"}


# ──── Legacy synchronous endpoints (kept for backwards compatibility) ────

@router.post("/extract/preview")
def extract_preview(req: ExtractRequest, db: Session = Depends(get_db)):
    """
    Preview the extracted dataset (limited rows).
    Returns columns and rows for display.
    """
    cohort, version = _get_cohort_and_version(db, req.cohort_id)
    cdm, conn = _get_cdm_conn(db, cohort.cdm_name)
    schema = _get_omop_schema(db, cdm)

    criteria = version.criteria_json
    cohort_has_visit = _cohort_has_same_visit(criteria)

    if req.same_visit_only and not cohort_has_visit:
        raise HTTPException(
            status_code=400,
            detail="Cannot use 'Same Visit Only' mode: this cohort was not built with sameVisit enabled.",
        )

    try:
        include_visit_id = cohort_has_visit
        cohort_sql = build_cohort_sql(criteria, schema, include_visit_id=include_visit_id)

        table_sels = [{"table": s.table, "columns": s.columns} for s in req.table_selections]
        extraction_sql = build_extraction_sql(
            cohort_sql=cohort_sql,
            omop_schema=schema,
            table_selections=table_sels,
            same_visit_only=req.same_visit_only,
            cohort_has_visit=cohort_has_visit,
        )

        limited_sql = f"{extraction_sql}\nLIMIT {req.preview_limit}"
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(limited_sql)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = [dict(r) for r in cur.fetchall()]

        count_sql = f"SELECT COUNT(*) FROM ({extraction_sql}) _cnt"
        with conn.cursor() as cur:
            cur.execute(count_sql)
            total_count = cur.fetchone()[0]

        return {
            "columns": columns,
            "rows": rows,
            "total_count": total_count,
            "preview_limit": req.preview_limit,
            "cohort_name": cohort.name,
            "sql": extraction_sql,
        }
    finally:
        conn.close()


@router.post("/extract/download")
def extract_download(req: ExtractRequest, db: Session = Depends(get_db)):
    """
    Download the full extracted dataset as CSV.
    """
    cohort, version = _get_cohort_and_version(db, req.cohort_id)
    cdm, conn = _get_cdm_conn(db, cohort.cdm_name)
    schema = _get_omop_schema(db, cdm)

    criteria = version.criteria_json
    cohort_has_visit = _cohort_has_same_visit(criteria)

    if req.same_visit_only and not cohort_has_visit:
        raise HTTPException(
            status_code=400,
            detail="Cannot use 'Same Visit Only' mode: this cohort was not built with sameVisit enabled.",
        )

    try:
        include_visit_id = cohort_has_visit
        cohort_sql = build_cohort_sql(criteria, schema, include_visit_id=include_visit_id)

        table_sels = [{"table": s.table, "columns": s.columns} for s in req.table_selections]
        extraction_sql = build_extraction_sql(
            cohort_sql=cohort_sql,
            omop_schema=schema,
            table_selections=table_sels,
            same_visit_only=req.same_visit_only,
            cohort_has_visit=cohort_has_visit,
        )

        def generate_csv():
            with conn.cursor(name="extract_cursor", cursor_factory=DictCursor) as cur:
                cur.itersize = 2000
                cur.execute(extraction_sql)
                # Named cursors: description is None until first fetch
                first_row = cur.fetchone()
                columns = [desc[0] for desc in cur.description] if cur.description else []

                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(columns)
                yield output.getvalue()

                if first_row:
                    output = io.StringIO()
                    writer = csv.writer(output)
                    writer.writerow([
                        v.isoformat() if hasattr(v, 'isoformat') else v
                        for v in (first_row[col] for col in columns)
                    ])
                    yield output.getvalue()

                for row in cur:
                    output = io.StringIO()
                    writer = csv.writer(output)
                    writer.writerow([
                        v.isoformat() if hasattr(v, 'isoformat') else v
                        for v in (row[col] for col in columns)
                    ])
                    yield output.getvalue()

            conn.close()

        filename = f"dataset_{cohort.name.replace(' ', '_')}_{cohort.id}.csv"
        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception:
        conn.close()
        raise
