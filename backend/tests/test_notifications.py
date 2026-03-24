"""Tests for Notifications endpoints.

Covers:
- CRUD operations (list, create, delete)
- Badge counts and item-level tracking
- Read/unread filters and mark-as-read operations
- Role-targeted notification visibility
- Type filtering and notification types endpoint
- Access control (admin-only create)
"""
import pytest
from unittest.mock import patch


# ── List / Create ──

def test_list_notifications_empty(client):
    resp = client.get("/api/notifications/")
    assert resp.status_code == 200
    assert resp.json()["notifications"] == []


def test_create_and_list(client):
    resp = client.post("/api/notifications/create", json={
        "username": "testuser",
        "type": "mapping_review",
        "title": "New mapping to review",
        "message": "5 new suggestions",
        "link": "/mapping",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    resp = client.get("/api/notifications/")
    assert len(resp.json()["notifications"]) == 1
    assert resp.json()["notifications"][0]["type"] == "mapping_review"
    assert resp.json()["notifications"][0]["read"] is False


def test_create_returns_all_fields(client):
    """Create response should contain the notification id."""
    resp = client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done",
        "title": "Done", "message": "msg", "link": "/q", "item_id": "Drug",
    })
    data = resp.json()
    assert "id" in data
    assert isinstance(data["id"], int)


def test_create_with_item_id(client):
    """item_id should be stored and returned in list."""
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done",
        "title": "Done", "item_id": "Condition",
    })
    resp = client.get("/api/notifications/")
    assert resp.json()["notifications"][0]["item_id"] == "Condition"


def test_list_ordered_by_newest_first(client):
    """Notifications should be returned newest first."""
    for i in range(3):
        client.post("/api/notifications/create", json={
            "username": "testuser", "type": "quality_done", "title": f"N{i}",
        })
    resp = client.get("/api/notifications/")
    titles = [n["title"] for n in resp.json()["notifications"]]
    assert titles == ["N2", "N1", "N0"]


def test_list_with_limit(client):
    """Limit parameter should cap the number of returned notifications."""
    for i in range(5):
        client.post("/api/notifications/create", json={
            "username": "testuser", "type": "quality_done", "title": f"N{i}",
        })
    resp = client.get("/api/notifications/", params={"limit": 2})
    assert len(resp.json()["notifications"]) == 2


def test_list_with_type_filter(client):
    """notif_type parameter should filter by notification type."""
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "mapping_review", "title": "M1",
    })
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done", "title": "Q1",
    })
    resp = client.get("/api/notifications/", params={"notif_type": "quality_done"})
    notifs = resp.json()["notifications"]
    assert len(notifs) == 1
    assert notifs[0]["type"] == "quality_done"


# ── Badges ──

def test_badges(client):
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "mapping_review", "title": "T1",
    })
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "mapping_review", "title": "T2",
    })
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done", "title": "Q1",
    })
    resp = client.get("/api/notifications/badges")
    assert resp.status_code == 200
    badges = resp.json()["badges"]
    assert badges.get("mapping") == 2
    assert badges.get("quality") == 1
    assert resp.json()["total"] == 3


def test_badges_empty(client):
    """No notifications should return empty badges with total 0."""
    resp = client.get("/api/notifications/badges")
    assert resp.json()["badges"] == {}
    assert resp.json()["total"] == 0


def test_badges_same_tab_aggregation(client):
    """Multiple types mapping to the same tab should be aggregated."""
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "mapping_review", "title": "T1",
    })
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "mapping_applied", "title": "T2",
    })
    resp = client.get("/api/notifications/badges")
    assert resp.json()["badges"]["mapping"] == 2


def test_badges_exclude_read(client):
    """Read notifications should not count in badges."""
    resp = client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done", "title": "Q1",
    })
    nid = resp.json()["id"]
    client.post(f"/api/notifications/{nid}/read")

    resp = client.get("/api/notifications/badges")
    assert resp.json()["total"] == 0


# ── Items endpoint ──

def test_items_empty(client):
    """No notifications should return empty items."""
    resp = client.get("/api/notifications/items")
    assert resp.status_code == 200
    assert resp.json()["items"] == {}


def test_items_returns_unread_item_ids(client):
    """Items endpoint should return item_ids grouped by type."""
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done",
        "title": "Done", "item_id": "Drug",
    })
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done",
        "title": "Done", "item_id": "Condition",
    })
    resp = client.get("/api/notifications/items")
    items = resp.json()["items"]
    assert "quality_done" in items
    item_ids = [i["item_id"] for i in items["quality_done"]]
    assert "Drug" in item_ids
    assert "Condition" in item_ids


def test_items_excludes_read(client):
    """Items endpoint should only return unread notifications."""
    resp = client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done",
        "title": "Done", "item_id": "Drug",
    })
    nid = resp.json()["id"]
    client.post(f"/api/notifications/{nid}/read")

    resp = client.get("/api/notifications/items")
    assert resp.json()["items"] == {}


def test_items_excludes_null_item_id(client):
    """Notifications without item_id should not appear in items endpoint."""
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done", "title": "No item",
    })
    resp = client.get("/api/notifications/items")
    assert resp.json()["items"] == {}


def test_items_filtered_by_type(client):
    """Items endpoint should support notif_type filter."""
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done",
        "title": "Q", "item_id": "Drug",
    })
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "mapping_review",
        "title": "M", "item_id": "Aspirin",
    })
    resp = client.get("/api/notifications/items", params={"notif_type": "mapping_review"})
    items = resp.json()["items"]
    assert "mapping_review" in items
    assert "quality_done" not in items


# ── Mark as read ──

def test_mark_as_read(client):
    resp = client.post("/api/notifications/create", json={
        "username": "testuser", "type": "cohort_shared", "title": "Shared",
    })
    nid = resp.json()["id"]
    resp = client.post(f"/api/notifications/{nid}/read")
    assert resp.status_code == 200

    resp = client.get("/api/notifications/badges")
    assert resp.json()["total"] == 0


def test_mark_as_read_not_found(client):
    """Marking a non-existent notification should return 404."""
    resp = client.post("/api/notifications/99999/read")
    assert resp.status_code == 404


def test_mark_item_read(client):
    """mark_item_read should mark all matching type+item_id as read."""
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done",
        "title": "Q1", "item_id": "Drug",
    })
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done",
        "title": "Q2", "item_id": "Drug",
    })
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done",
        "title": "Q3", "item_id": "Condition",
    })
    resp = client.post("/api/notifications/read-item", params={
        "notif_type": "quality_done", "item_id": "Drug",
    })
    assert resp.status_code == 200

    # Drug items read, Condition still unread
    resp = client.get("/api/notifications/badges")
    assert resp.json()["total"] == 1


def test_mark_all_read(client):
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "mapping_review", "title": "T1",
    })
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "mapping_review", "title": "T2",
    })
    resp = client.post("/api/notifications/read-all", params={"notif_type": "mapping_review"})
    assert resp.status_code == 200

    resp = client.get("/api/notifications/badges")
    assert resp.json()["total"] == 0


def test_mark_all_read_without_type(client):
    """Mark all read without type filter should mark everything."""
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "mapping_review", "title": "T1",
    })
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done", "title": "Q1",
    })
    resp = client.post("/api/notifications/read-all")
    assert resp.status_code == 200

    resp = client.get("/api/notifications/badges")
    assert resp.json()["total"] == 0


# ── Unread filter ──

def test_unread_only_filter(client):
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done", "title": "Done",
    })
    nid = client.get("/api/notifications/").json()["notifications"][0]["id"]
    client.post(f"/api/notifications/{nid}/read")

    resp = client.get("/api/notifications/", params={"unread_only": True})
    assert len(resp.json()["notifications"]) == 0

    resp = client.get("/api/notifications/")
    assert len(resp.json()["notifications"]) == 1


# ── Delete ──

def test_delete_notification(client):
    """Deleting a notification should remove it from the list."""
    resp = client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done", "title": "Del",
    })
    nid = resp.json()["id"]

    resp = client.delete(f"/api/notifications/{nid}")
    assert resp.status_code == 200

    resp = client.get("/api/notifications/")
    assert len(resp.json()["notifications"]) == 0


def test_delete_notification_not_found(client):
    """Deleting a non-existent notification should return 404."""
    resp = client.delete("/api/notifications/99999")
    assert resp.status_code == 404


def test_delete_all_read(client):
    """Delete all read should only remove read notifications."""
    # Create 2 notifications, mark one as read
    resp1 = client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done", "title": "Read",
    })
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done", "title": "Unread",
    })
    nid = resp1.json()["id"]
    client.post(f"/api/notifications/{nid}/read")

    resp = client.delete("/api/notifications/")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1

    # Unread one should remain
    resp = client.get("/api/notifications/")
    assert len(resp.json()["notifications"]) == 1
    assert resp.json()["notifications"][0]["title"] == "Unread"


def test_delete_all_read_empty(client):
    """Delete all read with no read notifications should delete 0."""
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done", "title": "Unread",
    })
    resp = client.delete("/api/notifications/")
    assert resp.json()["deleted"] == 0


# ── Types endpoint ──

def test_list_notification_types(client):
    """Types endpoint should return the TYPE_TO_TAB mapping."""
    resp = client.get("/api/notifications/types")
    assert resp.status_code == 200
    types = resp.json()["types"]
    assert types["mapping_review"] == "mapping"
    assert types["quality_done"] == "quality"
    assert types["cohort_shared"] == "cohorts"
    assert types["access_granted"] == "cdm"
    assert types["extraction_done"] == "data"


# ── Role-targeted notifications ──

def test_role_targeted_visible_to_users_with_role(client):
    """Notifications targeted at 'admin' role should be visible to admin users."""
    from tests.conftest import TestSession
    from db.models import Notification

    db = TestSession()
    try:
        db.add(Notification(
            username="system", type="access_request",
            title="Access request", target_role="admin",
        ))
        db.commit()
    finally:
        db.close()

    # testuser has admin role (from conftest default)
    resp = client.get("/api/notifications/")
    assert len(resp.json()["notifications"]) == 1
    assert resp.json()["notifications"][0]["type"] == "access_request"


def test_role_targeted_invisible_to_other_roles(client):
    """Role-targeted notifications should not be visible to users without that role."""
    from tests.conftest import TestSession
    from db.models import Notification

    db = TestSession()
    try:
        db.add(Notification(
            username="system", type="access_request",
            title="Access request", target_role="data-manager",
        ))
        db.commit()
    finally:
        db.close()

    # testuser has admin role, not data-manager
    resp = client.get("/api/notifications/", headers={"X-Test-Roles": "viewer"})
    notifs = [n for n in resp.json()["notifications"] if n["type"] == "access_request"]
    assert len(notifs) == 0


def test_role_targeted_badges_counted(client):
    """Role-targeted notifications should count in badges."""
    from tests.conftest import TestSession
    from db.models import Notification

    db = TestSession()
    try:
        db.add(Notification(
            username="system", type="access_request",
            title="Request", target_role="admin",
        ))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/notifications/badges")
    assert resp.json()["total"] == 1


# ── Access control ──

def test_create_notification_non_admin_forbidden(client):
    """Non-admin users should not be able to create notifications."""
    resp = client.post(
        "/api/notifications/create",
        json={"username": "testuser", "type": "test", "title": "T"},
        headers={"X-Test-Roles": "viewer"},
    )
    assert resp.status_code == 403


def test_create_notification_data_manager_allowed(client):
    """data-manager role should also be able to create notifications."""
    resp = client.post(
        "/api/notifications/create",
        json={"username": "testuser", "type": "test", "title": "T"},
        headers={"X-Test-Roles": "data-manager"},
    )
    assert resp.status_code == 200


def test_other_user_notification_not_visible(client):
    """Notifications for other users should not be visible."""
    from tests.conftest import TestSession
    from db.models import Notification

    db = TestSession()
    try:
        db.add(Notification(
            username="otheruser", type="quality_done", title="Other's notif",
        ))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/notifications/")
    assert len(resp.json()["notifications"]) == 0


def test_cannot_mark_other_user_notification_read(client):
    """Cannot mark another user's notification as read."""
    from tests.conftest import TestSession
    from db.models import Notification

    db = TestSession()
    try:
        notif = Notification(username="otheruser", type="quality_done", title="Other")
        db.add(notif)
        db.commit()
        db.refresh(notif)
        nid = notif.id
    finally:
        db.close()

    resp = client.post(f"/api/notifications/{nid}/read")
    assert resp.status_code == 404


def test_cannot_delete_other_user_notification(client):
    """Cannot delete another user's notification."""
    from tests.conftest import TestSession
    from db.models import Notification

    db = TestSession()
    try:
        notif = Notification(username="otheruser", type="quality_done", title="Other")
        db.add(notif)
        db.commit()
        db.refresh(notif)
        nid = notif.id
    finally:
        db.close()

    resp = client.delete(f"/api/notifications/{nid}")
    assert resp.status_code == 404
