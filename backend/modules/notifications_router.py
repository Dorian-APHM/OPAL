"""
Notifications endpoints.

In-app notification system with per-tab badge counts and item-level tracking.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from db.app_db import get_db
from db.models import Notification

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/notifications", tags=["notifications"])

# Map notification types to sidebar tabs
TYPE_TO_TAB = {
    "mapping_review": "mapping",
    "mapping_applied": "mapping",
    "quality_done": "quality",
    "cohort_shared": "cohorts",
    "cohort_deleted": "cohorts",
    "cohort_updated": "cohorts",
    # "group_added" excluded: ephemeral info, no badge needed
    "group_removed": "users",
    "access_request": "users",
    "access_granted": "cdm",
    "access_revoked": "cdm",
    "cdm_created": "cdm",
    "cdm_updated": "cdm",
    "cdm_deleted": "cdm",
    "extraction_done": "data",
}


def _user_filter(request: Request):
    """Build filter clauses for user-targeted + role-targeted notifications."""
    from sqlalchemy import or_
    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "anonymous")
    user_roles = user.get("roles", [])
    filters = [Notification.username == username]
    for role in user_roles:
        filters.append(Notification.target_role == role)
    return or_(*filters), username


class CreateNotificationRequest(BaseModel):
    username: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    message: str = ""
    link: str = ""
    item_id: str = ""


@router.get("/")
def list_notifications(
    request: Request,
    unread_only: bool = False,
    notif_type: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List notifications for the current user (includes role-targeted)."""
    user_or, _ = _user_filter(request)
    q = db.query(Notification).filter(user_or)
    if unread_only:
        q = q.filter(Notification.read == 0)
    if notif_type:
        q = q.filter(Notification.type == notif_type)
    notifications = q.order_by(Notification.created_at.desc()).limit(limit).all()

    return {
        "notifications": [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "message": n.message,
                "link": n.link,
                "item_id": n.item_id,
                "read": bool(n.read),
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifications
        ]
    }


@router.get("/badges")
def get_badge_counts(
    request: Request,
    db: Session = Depends(get_db),
):
    """Get unread notification counts grouped by type (for sidebar badges)."""
    user_or, _ = _user_filter(request)

    counts = (
        db.query(Notification.type, func.count(Notification.id))
        .filter(user_or, Notification.read == 0)
        .group_by(Notification.type)
        .all()
    )

    badges = {}
    for notif_type, count in counts:
        tab = TYPE_TO_TAB.get(notif_type, notif_type)
        badges[tab] = badges.get(tab, 0) + count

    return {"badges": badges, "total": sum(c for _, c in counts)}


@router.get("/items")
def get_unread_items(
    request: Request,
    notif_type: str | None = None,
    db: Session = Depends(get_db),
):
    """Get unread item_ids grouped by type. Used by pages to show red dots on specific elements."""
    user_or, _ = _user_filter(request)

    q = db.query(Notification.type, Notification.item_id, Notification.id).filter(
        user_or, Notification.read == 0, Notification.item_id.isnot(None)
    )
    if notif_type:
        q = q.filter(Notification.type == notif_type)

    rows = q.all()
    # Return { type: [{ item_id, notif_id }] }
    items: dict[str, list[dict]] = {}
    for ntype, item_id, nid in rows:
        items.setdefault(ntype, []).append({"item_id": item_id, "notif_id": nid})

    return {"items": items}


@router.post("/{notification_id}/read")
def mark_as_read(notification_id: int, request: Request, db: Session = Depends(get_db)):
    """Mark a notification as read."""
    user_or, _ = _user_filter(request)
    notif = db.query(Notification).filter(Notification.id == notification_id, user_or).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.read = 1
    db.commit()
    return {"status": "ok"}


@router.post("/read-item")
def mark_item_read(
    request: Request,
    notif_type: str = "",
    item_id: str = "",
    db: Session = Depends(get_db),
):
    """Mark all unread notifications matching type + item_id as read."""
    user_or, _ = _user_filter(request)

    q = db.query(Notification).filter(user_or, Notification.read == 0)
    if notif_type:
        q = q.filter(Notification.type == notif_type)
    if item_id:
        q = q.filter(Notification.item_id == item_id)
    q.update({"read": 1}, synchronize_session="fetch")
    db.commit()
    return {"status": "ok"}


@router.post("/read-all")
def mark_all_read(
    request: Request,
    notif_type: str | None = None,
    db: Session = Depends(get_db),
):
    """Mark all notifications as read for current user, optionally filtered by type."""
    user_or, _ = _user_filter(request)

    q = db.query(Notification).filter(user_or, Notification.read == 0)
    if notif_type:
        q = q.filter(Notification.type == notif_type)
    q.update({"read": 1}, synchronize_session="fetch")
    db.commit()
    return {"status": "ok"}


@router.post("/create")
def create_notification(req: CreateNotificationRequest, request: Request, db: Session = Depends(get_db)):
    """Create a notification (internal/admin use)."""
    user = getattr(request.state, "user", {})
    user_roles = user.get("roles", [])
    if not any(r in ("admin", "data-manager") for r in user_roles):
        raise HTTPException(status_code=403, detail="Only admin or data-manager can create notifications")
    notif = Notification(
        username=req.username,
        type=req.type,
        title=req.title,
        message=req.message,
        link=req.link,
        item_id=req.item_id or None,
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)

    # Push via WebSocket
    from utils.ws_manager import _push_via_main_loop
    _push_via_main_loop(req.username, {
        "id": notif.id, "type": notif.type, "title": notif.title,
        "message": notif.message, "link": notif.link, "item_id": notif.item_id,
        "read": False, "created_at": notif.created_at.isoformat() if notif.created_at else None,
    })

    return {"status": "ok", "id": notif.id}


@router.delete("/{notification_id}")
def delete_notification(notification_id: int, request: Request, db: Session = Depends(get_db)):
    """Delete a specific notification."""
    user_or, _ = _user_filter(request)
    notif = db.query(Notification).filter(Notification.id == notification_id, user_or).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    db.delete(notif)
    db.commit()
    return {"status": "ok"}


@router.delete("/")
def delete_all_read(request: Request, db: Session = Depends(get_db)):
    """Delete all read notifications for the current user."""
    user_or, _ = _user_filter(request)
    deleted = db.query(Notification).filter(user_or, Notification.read == 1).delete(synchronize_session="fetch")
    db.commit()
    return {"status": "ok", "deleted": deleted}


@router.get("/types")
def list_notification_types():
    """Return all known notification types and their tab mappings."""
    return {"types": TYPE_TO_TAB}


# ── Notification Preferences ──

@router.get("/preferences")
def get_preferences(request: Request, db: Session = Depends(get_db)):
    """Get notification preferences for the current user."""
    from db.models import NotificationPreference
    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "anonymous")

    prefs = db.query(NotificationPreference).filter(
        NotificationPreference.username == username,
    ).all()

    # Build a map: type → enabled (default True for types not in DB)
    pref_map = {p.notif_type: bool(p.enabled) for p in prefs}
    result = {}
    for notif_type in TYPE_TO_TAB:
        result[notif_type] = pref_map.get(notif_type, True)
    # Include non-tabbed types
    result["group_added"] = pref_map.get("group_added", True)
    result["group_removed"] = pref_map.get("group_removed", True)

    return {"preferences": result}


class PreferenceUpdateRequest(BaseModel):
    notif_type: str = Field(..., min_length=1)
    enabled: bool


@router.post("/preferences")
def update_preference(req: PreferenceUpdateRequest, request: Request, db: Session = Depends(get_db)):
    """Update a notification preference for the current user."""
    from db.models import NotificationPreference
    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "anonymous")

    pref = db.query(NotificationPreference).filter(
        NotificationPreference.username == username,
        NotificationPreference.notif_type == req.notif_type,
    ).first()

    if pref:
        pref.enabled = 1 if req.enabled else 0
    else:
        db.add(NotificationPreference(
            username=username,
            notif_type=req.notif_type,
            enabled=1 if req.enabled else 0,
        ))

    db.commit()
    return {"status": "ok", "notif_type": req.notif_type, "enabled": req.enabled}
