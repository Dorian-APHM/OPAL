"""
User Favorites endpoints.

Allows users to bookmark cohorts, concepts, queries, CDMs.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.app_db import get_db
from db.models import UserFavorite

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/favorites", tags=["favorites"])


class AddFavoriteRequest(BaseModel):
    item_type: str = Field(..., min_length=1)  # cohort, concept, query, cdm
    item_id: str = Field(..., min_length=1)
    item_label: str = ""
    item_meta: dict | None = None


@router.get("/")
def list_favorites(
    request: Request,
    item_type: str | None = None,
    db: Session = Depends(get_db),
):
    """List favorites for the current user."""
    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "anonymous")

    q = db.query(UserFavorite).filter(UserFavorite.username == username)
    if item_type:
        q = q.filter(UserFavorite.item_type == item_type)
    favs = q.order_by(UserFavorite.created_at.desc()).all()

    return {
        "favorites": [
            {
                "id": f.id,
                "item_type": f.item_type,
                "item_id": f.item_id,
                "item_label": f.item_label,
                "item_meta": f.item_meta,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in favs
        ]
    }


@router.post("/")
def add_favorite(req: AddFavoriteRequest, request: Request, db: Session = Depends(get_db)):
    """Add a favorite."""
    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "anonymous")

    # Check duplicate
    existing = db.query(UserFavorite).filter(
        UserFavorite.username == username,
        UserFavorite.item_type == req.item_type,
        UserFavorite.item_id == req.item_id,
    ).first()
    if existing:
        return {"status": "already_exists", "id": existing.id}

    fav = UserFavorite(
        username=username,
        item_type=req.item_type,
        item_id=req.item_id,
        item_label=req.item_label,
        item_meta=req.item_meta,
    )
    db.add(fav)
    db.commit()
    return {"status": "ok", "id": fav.id}


@router.delete("/{favorite_id}")
def remove_favorite(favorite_id: int, request: Request, db: Session = Depends(get_db)):
    """Remove a favorite."""
    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "anonymous")

    fav = db.query(UserFavorite).filter(
        UserFavorite.id == favorite_id,
        UserFavorite.username == username,
    ).first()
    if not fav:
        raise HTTPException(status_code=404, detail="Favorite not found")
    db.delete(fav)
    db.commit()
    return {"status": "ok"}
