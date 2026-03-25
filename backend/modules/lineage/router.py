"""
Lineage endpoints — upload ETL docs, retrieve lineage graphs.

Stores parsed lineage per CDM in the app database.
"""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from sqlalchemy.orm import Session

from db.app_db import get_db
from db.models import LineageDoc
from modules.lineage.parser import build_lineage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/lineage", tags=["lineage"])


def _parse_html_bytes(content: bytes, filename: str) -> dict:
    """Write HTML to a temp file and parse it."""
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".html", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        logger.info("Parsing ETL doc: %s (%d bytes)", tmp_path, len(content))
        result = build_lineage(tmp_path)
        logger.info("Parsed: %d nodes, %d edges", result["metadata"]["total_nodes"], result["metadata"]["total_edges"])
        return result
    finally:
        os.unlink(tmp_path)


@router.post("/upload")
async def upload_lineage_doc(
    request: Request,
    cdm_name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload an ETL HTML doc and parse it into a lineage graph for a CDM."""
    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "anonymous")

    if not file.filename or not file.filename.endswith(".html"):
        raise HTTPException(status_code=400, detail="Only HTML ETL docs are supported")

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 20MB)")

    try:
        lineage = _parse_html_bytes(content, file.filename)
    except Exception as e:
        logger.exception("Failed to parse ETL doc")
        raise HTTPException(status_code=422, detail=f"Failed to parse ETL doc: {e}")

    # Upsert: replace existing lineage for this CDM
    existing = db.query(LineageDoc).filter(LineageDoc.cdm_name == cdm_name).first()
    if existing:
        existing.filename = file.filename
        existing.lineage_json = lineage
        existing.uploaded_by = username
        existing.uploaded_at = datetime.now(timezone.utc)
    else:
        doc = LineageDoc(
            cdm_name=cdm_name,
            filename=file.filename,
            lineage_json=lineage,
            uploaded_by=username,
        )
        db.add(doc)

    db.commit()

    return {
        "status": "ok",
        "cdm_name": cdm_name,
        "metadata": lineage["metadata"],
    }


@router.get("/{cdm_name}")
def get_lineage(cdm_name: str, db: Session = Depends(get_db)):
    """Get the full lineage graph for a CDM."""
    doc = db.query(LineageDoc).filter(LineageDoc.cdm_name == cdm_name).first()
    if not doc:
        raise HTTPException(status_code=404, detail="No lineage doc found for this CDM")

    return {
        "cdm_name": doc.cdm_name,
        "filename": doc.filename,
        "uploaded_by": doc.uploaded_by,
        "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        "lineage": doc.lineage_json,
    }


@router.get("/{cdm_name}/omop-chains")
def get_omop_chains(cdm_name: str, table: str | None = None, db: Session = Depends(get_db)):
    """Get OMOP lineage chains, optionally filtered to a single table."""
    doc = db.query(LineageDoc).filter(LineageDoc.cdm_name == cdm_name).first()
    if not doc:
        raise HTTPException(status_code=404, detail="No lineage doc found for this CDM")

    chains = doc.lineage_json.get("omop_chains", {})
    if table:
        key = table if table.startswith("omop_cdm.") else f"omop_cdm.{table}"
        if key not in chains:
            raise HTTPException(status_code=404, detail=f"No chain found for {key}")
        return {"table": key, "chain": chains[key]}

    return {"chains": chains}


@router.get("/{cdm_name}/summary")
def get_lineage_summary(cdm_name: str, db: Session = Depends(get_db)):
    """Get a summary of the lineage: counts, OMOP tables, source systems."""
    doc = db.query(LineageDoc).filter(LineageDoc.cdm_name == cdm_name).first()
    if not doc:
        raise HTTPException(status_code=404, detail="No lineage doc found for this CDM")

    lineage = doc.lineage_json
    nodes = lineage.get("nodes", {})
    edges = lineage.get("edges", [])

    layers = {}
    for n in nodes.values():
        layer = n.get("layer", "unknown")
        layers[layer] = layers.get(layer, 0) + 1

    omop_tables = sorted(k for k, v in nodes.items() if v.get("layer") == "omop")

    return {
        "cdm_name": cdm_name,
        "filename": doc.filename,
        "uploaded_by": doc.uploaded_by,
        "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "layers": layers,
        "omop_tables": omop_tables,
        "source_systems": lineage.get("source_systems", {}),
    }


@router.delete("/{cdm_name}")
def delete_lineage(cdm_name: str, request: Request, db: Session = Depends(get_db)):
    """Delete lineage doc for a CDM."""
    doc = db.query(LineageDoc).filter(LineageDoc.cdm_name == cdm_name).first()
    if not doc:
        raise HTTPException(status_code=404, detail="No lineage doc found for this CDM")
    db.delete(doc)
    db.commit()
    return {"status": "ok"}
