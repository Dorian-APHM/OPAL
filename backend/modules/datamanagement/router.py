"""
Data Management module API endpoints.

Allows users to select a saved cohort, pick OMOP tables/columns,
and extract a dataset (one CSV per table, packaged as ZIP).

Extraction runs as a background task with progress polling.
"""
import csv
import io
import logging
import os
import tempfile
import threading
import time
import uuid
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from utils.rate_limit import limiter
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func
from psycopg2.extras import DictCursor

from db.app_db import get_db, SessionLocal
from db.models import CdmConfig, Cohort, CohortVersion, AnalysisSettings
from db.omop_connector import get_omop_connection
from utils.crypto import decrypt_password
from utils.cdm_helper import check_cdm_access
from utils.notifications import notify
from config import DEFAULT_OMOP_SCHEMA
from modules.cohort.sql_builder import build_cohort_sql
from modules.datamanagement.extractor import (
    list_available_tables,
    get_table_columns,
    build_table_sql,
    build_schema,
    EXTRACTABLE_TABLES,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/datamanagement", tags=["datamanagement"])


# ──── Helpers ────

def _assert_task_owner(request: Request, task: dict) -> None:
    """Raise HTTP 403 if the current user is not the task owner (or admin/data-manager)."""
    from config import AUTH_ENABLED
    if not AUTH_ENABLED:
        return
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = user.get("preferred_username", "")
    roles = user.get("roles", []) or user.get("realm_access", {}).get("roles", [])
    if username == task.get("username") or any(r in ("admin", "data-manager") for r in roles):
        return
    raise HTTPException(status_code=403, detail="Access denied: not your extraction task")

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


class SchemaRequest(BaseModel):
    table_selections: list[TableSelection] = Field(..., min_length=1)


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
    max_ver_subq = (
        db.query(
            CohortVersion.cohort_id,
            func.max(CohortVersion.version).label("max_version"),
        )
        .group_by(CohortVersion.cohort_id)
        .subquery()
    )
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


# ──── BDR Schema endpoint ────

@router.post("/extract/schema")
def extract_schema(
    req: SchemaRequest,
    cdm_name: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    """
    Return the relational schema (BDR) for the selected tables.
    Shows tables, columns, data types, and FK relationships.
    """
    cdm, conn = _get_cdm_conn(db, cdm_name)
    schema = _get_omop_schema(db, cdm)
    try:
        # Fetch full column metadata for each selected table
        all_columns: dict[str, list[dict]] = {}
        for sel in req.table_selections:
            all_columns[sel.table] = get_table_columns(conn, schema, sel.table)

        table_sels = [{"table": s.table, "columns": s.columns} for s in req.table_selections]
        bdr = build_schema(table_sels, all_columns)
        return bdr
    finally:
        conn.close()


# ──── Background extraction (ZIP with 1 CSV per table) ────

@router.post("/extract/start")
@limiter.limit("3/minute")
def extract_start(req: ExtractRequest, request: Request, db: Session = Depends(get_db)):
    """
    Launch extraction as a background task.
    Returns a task_id for polling via /extract/status/{task_id}.

    Produces a ZIP file containing one CSV per selected table.
    """
    cohort, version = _get_cohort_and_version(db, req.cohort_id)
    cdm_name = cohort.cdm_name
    check_cdm_access(request, cdm_name)
    cohort_name = cohort.name

    criteria = version.criteria_json
    cohort_has_visit = _cohort_has_same_visit(criteria)

    if req.same_visit_only and not cohort_has_visit:
        raise HTTPException(
            status_code=400,
            detail="Cannot use 'Same Visit Only' mode: this cohort was not built with sameVisit enabled.",
        )

    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "anonymous")

    task_id = str(uuid.uuid4())
    num_tables = len(req.table_selections)

    with _extractions_lock:
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
            "total": num_tables,
            "current_step": "",
            "result": None,
            "zip_path": None,
            "zip_filename": None,
            "completed_at": None,
            "error": None,
        }

    cohort_id = req.cohort_id
    same_visit_only = req.same_visit_only
    table_sels_raw = [{"table": s.table, "columns": s.columns} for s in req.table_selections]

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

            # Build ZIP with one CSV per table
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip", prefix="opal_extract_")
            os.close(tmp_fd)

            table_row_counts: dict[str, int] = {}

            try:
                with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for idx, sel in enumerate(table_sels_raw):
                        tbl_name = sel["table"]
                        columns = sel["columns"]
                        _progress(idx, num_tables, f"Extracting {tbl_name}...")

                        table_sql = build_table_sql(
                            cohort_sql=cohort_sql,
                            omop_schema=schema,
                            table_name=tbl_name,
                            columns=columns,
                            same_visit_only=same_visit_only,
                            cohort_has_visit=ch_visit,
                        )

                        # Stream rows into a CSV buffer, then write to ZIP
                        csv_buf = io.StringIO()
                        writer = csv.writer(csv_buf)
                        row_count = 0

                        with conn.cursor(
                            name=f"extract_{tbl_name}",
                            cursor_factory=DictCursor,
                        ) as cur:
                            cur.itersize = 2000
                            cur.execute(table_sql)
                            first_row = cur.fetchone()
                            csv_columns = (
                                [desc[0] for desc in cur.description]
                                if cur.description else columns
                            )
                            writer.writerow(csv_columns)
                            if first_row:
                                writer.writerow([
                                    v.isoformat() if hasattr(v, "isoformat") else v
                                    for v in (first_row[col] for col in csv_columns)
                                ])
                                row_count += 1
                            for row in cur:
                                writer.writerow([
                                    v.isoformat() if hasattr(v, "isoformat") else v
                                    for v in (row[col] for col in csv_columns)
                                ])
                                row_count += 1

                        zf.writestr(f"{tbl_name}.csv", csv_buf.getvalue())
                        table_row_counts[tbl_name] = row_count

            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            _progress(num_tables, num_tables, "Done")

            total_rows = sum(table_row_counts.values())
            filename = f"dataset_{cohort_name.replace(' ', '_')}_{cohort_id}.zip"

            with _extractions_lock:
                task = _active_extractions.get(task_id)
                if task:
                    task["result"] = {
                        "table_row_counts": table_row_counts,
                        "total_rows": total_rows,
                        "num_tables": num_tables,
                        "cohort_name": cohort_name,
                    }
                    task["zip_path"] = tmp_path
                    task["zip_filename"] = filename
                    task["completed_at"] = time.time()
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
                        message=f"{total_rows} rows across {num_tables} tables extracted from cohort '{cohort_name}'",
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

    from utils.thread_pool import submit_task
    submit_task(_worker)

    return {"task_id": task_id, "status": "running"}


@router.get("/extract/status/{task_id}")
def extract_status(task_id: str, request: Request):
    """Poll the status of an extraction task."""
    with _extractions_lock:
        task = _active_extractions.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    _assert_task_owner(request, task)

    resp: dict = {
        "task_id": task_id,
        "status": task["status"],
        "completed": task.get("completed", 0),
        "total": task.get("total", 0),
        "current_step": task.get("current_step", ""),
        "cohort_name": task.get("cohort_name", ""),
    }
    if task["status"] == "completed":
        resp["result"] = task["result"]
    elif task["status"] == "error":
        resp["error"] = task["error"]
        with _extractions_lock:
            _active_extractions.pop(task_id, None)
    return resp


@router.get("/extract/download/{task_id}")
def extract_download_task(task_id: str, request: Request):
    """Download the ZIP produced by a completed extraction task."""
    with _extractions_lock:
        task = _active_extractions.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    _assert_task_owner(request, task)
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="Extraction not yet completed")

    zip_path = task.get("zip_path")
    filename = task.get("zip_filename", "dataset.zip")
    if not zip_path or not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail="ZIP data not available")

    file_size = os.path.getsize(zip_path)

    def _stream_and_cleanup():
        try:
            with open(zip_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
        finally:
            try:
                os.unlink(zip_path)
            except OSError:
                pass
            with _extractions_lock:
                _active_extractions.pop(task_id, None)

    return StreamingResponse(
        _stream_and_cleanup(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(file_size),
        },
    )


@router.post("/extract/cancel/{task_id}")
def extract_cancel(task_id: str, request: Request):
    """Cancel/clean up an extraction task."""
    with _extractions_lock:
        task = _active_extractions.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    _assert_task_owner(request, task)
    with _extractions_lock:
        task = _active_extractions.pop(task_id, None)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    zip_path = task.get("zip_path")
    if zip_path:
        try:
            os.unlink(zip_path)
        except OSError:
            pass
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
                "total": task.get("total", 0),
                "current_step": task.get("current_step", ""),
            }
    for tid, task in items:
        if task["status"] == "completed":
            return {
                "task_id": tid,
                "status": "completed",
                "cdm_name": task.get("cdm_name"),
                "cohort_name": task.get("cohort_name"),
                "completed": task.get("total", 0),
                "total": task.get("total", 0),
                "current_step": "Done",
            }
    return {"task_id": None, "status": "none"}
