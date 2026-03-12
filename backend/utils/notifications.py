"""
Shared notification helper.

Provides a single `notify()` function used across modules to create
in-app notifications without duplicating code.
"""
from sqlalchemy.orm import Session
from db.models import Notification


def notify(db: Session, username: str, notif_type: str, title: str, message: str = "", link: str = "", target_role: str = "", item_id: str = ""):
    """Create an in-app notification for a user or a role.

    If target_role is set, the notification is visible to ALL users with that role
    (username is stored for provenance but filtering uses target_role).
    item_id identifies the specific element (domain name, cohort id, request id, etc.)
    so the frontend can show a red dot on the exact element.
    """
    db.add(Notification(
        username=username,
        type=notif_type,
        title=title,
        message=message,
        link=link,
        target_role=target_role or None,
        item_id=item_id or None,
    ))
