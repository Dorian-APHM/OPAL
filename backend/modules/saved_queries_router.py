"""
Saved SQL Queries endpoints.

CRUD for named SQL queries in the SQL Editor.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.app_db import get_db
from db.models import SavedQuery

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/saved-queries", tags=["saved-queries"])


class SaveQueryRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=500)
    sql: str = Field(..., min_length=1)
    description: str = ""


class UpdateQueryRequest(BaseModel):
    name: str | None = None
    sql: str | None = None
    description: str | None = None


@router.get("/")
def list_queries(
    cdm_name: str | None = None,
    request: Request = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List saved queries, optionally filtered by CDM."""
    q = db.query(SavedQuery)
    if cdm_name:
        q = q.filter(SavedQuery.cdm_name == cdm_name)
    total = q.count()
    queries = q.order_by(SavedQuery.updated_at.desc()).offset(offset).limit(limit).all()
    return {
        "queries": [
            {
                "id": sq.id,
                "cdm_name": sq.cdm_name,
                "name": sq.name,
                "sql": sq.sql,
                "description": sq.description,
                "created_by": sq.created_by,
                "created_at": sq.created_at.isoformat() if sq.created_at else None,
                "updated_at": sq.updated_at.isoformat() if sq.updated_at else None,
            }
            for sq in queries
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/")
def create_query(req: SaveQueryRequest, request: Request, db: Session = Depends(get_db)):
    """Save a new query."""
    user = getattr(request.state, "user", {})
    sq = SavedQuery(
        cdm_name=req.cdm_name,
        name=req.name,
        sql=req.sql,
        description=req.description,
        created_by=user.get("preferred_username", "system"),
    )
    db.add(sq)
    db.commit()
    return {"status": "ok", "id": sq.id, "name": sq.name}


@router.put("/{query_id}")
def update_query(query_id: int, req: UpdateQueryRequest, request: Request, db: Session = Depends(get_db)):
    """Update a saved query."""
    sq = db.query(SavedQuery).filter(SavedQuery.id == query_id).first()
    if not sq:
        raise HTTPException(status_code=404, detail="Query not found")
    user = getattr(request.state, "user", {})
    current_user = user.get("preferred_username", "system")
    if sq.created_by != current_user:
        raise HTTPException(status_code=403, detail="Not authorized to update this query")
    if req.name is not None:
        sq.name = req.name
    if req.sql is not None:
        sq.sql = req.sql
    if req.description is not None:
        sq.description = req.description
    db.commit()
    return {"status": "ok", "id": sq.id}


@router.delete("/{query_id}")
def delete_query(query_id: int, request: Request, db: Session = Depends(get_db)):
    """Delete a saved query."""
    sq = db.query(SavedQuery).filter(SavedQuery.id == query_id).first()
    if not sq:
        raise HTTPException(status_code=404, detail="Query not found")
    user = getattr(request.state, "user", {})
    current_user = user.get("preferred_username", "system")
    if sq.created_by != current_user:
        raise HTTPException(status_code=403, detail="Not authorized to delete this query")
    db.delete(sq)
    db.commit()
    return {"status": "ok"}
