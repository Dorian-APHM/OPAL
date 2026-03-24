"""
Shared notification helper.

Provides a single `notify()` function used across modules to create
in-app notifications and push them in real time via WebSocket.
"""
from sqlalchemy.orm import Session
from db.models import Notification


def notify(db: Session, username: str, notif_type: str, title: str, message: str = "", link: str = "", target_role: str = "", item_id: str = ""):
    """Create an in-app notification for a user or a role and push it in real time.

    If target_role is set, the notification is visible to ALL users with that role
    (username is stored for provenance but filtering uses target_role).
    item_id identifies the specific element (domain name, cohort id, request id, etc.)
    so the frontend can show a red dot on the exact element.

    Respects user notification preferences — skips if user muted this type.
    """
    from db.models import NotificationPreference
    # Check if user has muted this notification type
    if not target_role:
        pref = db.query(NotificationPreference).filter(
            NotificationPreference.username == username,
            NotificationPreference.notif_type == notif_type,
            NotificationPreference.enabled == 0,
        ).first()
        if pref:
            return  # User muted this type

    notif = Notification(
        username=username,
        type=notif_type,
        title=title,
        message=message,
        link=link,
        target_role=target_role or None,
        item_id=item_id or None,
    )
    db.add(notif)
    db.flush()  # Get the ID assigned

    # Push via WebSocket in real time
    from utils.ws_manager import _push_via_main_loop
    notif_data = {
        "id": notif.id,
        "type": notif.type,
        "title": notif.title,
        "message": notif.message,
        "link": notif.link,
        "item_id": notif.item_id,
        "read": False,
        "created_at": notif.created_at.isoformat() if notif.created_at else None,
    }
    _push_via_main_loop(username, notif_data, target_role or "")
