"""Tests for notification preferences and the notify() helper."""
import pytest
from unittest.mock import patch

from db.models import NotificationPreference, Notification


# ── Preferences API ──

def test_get_preferences_defaults(client):
    """All preferences should default to True when no DB entries exist."""
    resp = client.get("/api/notifications/preferences")
    assert resp.status_code == 200
    prefs = resp.json()["preferences"]
    assert prefs["mapping_review"] is True
    assert prefs["quality_done"] is True
    assert prefs["cohort_shared"] is True
    assert prefs["group_added"] is True
    assert prefs["group_removed"] is True


def test_update_preference_mute(client):
    """Muting a notification type should persist."""
    resp = client.post("/api/notifications/preferences", json={
        "notif_type": "mapping_review",
        "enabled": False,
    })
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    resp = client.get("/api/notifications/preferences")
    assert resp.json()["preferences"]["mapping_review"] is False


def test_update_preference_unmute(client):
    """Unmuting a previously muted type should work."""
    client.post("/api/notifications/preferences", json={
        "notif_type": "quality_done", "enabled": False,
    })
    resp = client.post("/api/notifications/preferences", json={
        "notif_type": "quality_done", "enabled": True,
    })
    assert resp.status_code == 200

    resp = client.get("/api/notifications/preferences")
    assert resp.json()["preferences"]["quality_done"] is True


def test_update_preference_idempotent(client):
    """Updating the same preference twice should not create duplicates."""
    client.post("/api/notifications/preferences", json={
        "notif_type": "cohort_shared", "enabled": False,
    })
    client.post("/api/notifications/preferences", json={
        "notif_type": "cohort_shared", "enabled": False,
    })

    resp = client.get("/api/notifications/preferences")
    assert resp.json()["preferences"]["cohort_shared"] is False


# ── notify() helper ──

def test_notify_creates_notification(client):
    """notify() should create a Notification row in the DB."""
    from utils.notifications import notify
    from tests.conftest import TestSession

    db = TestSession()
    try:
        with patch("utils.ws_manager._push_via_main_loop"):
            notify(db, "testuser", "quality_done", "Analysis complete", message="Done", link="/quality")
        db.commit()

        notif = db.query(Notification).first()
        assert notif is not None
        assert notif.username == "testuser"
        assert notif.type == "quality_done"
        assert notif.title == "Analysis complete"
        assert notif.message == "Done"
        assert notif.link == "/quality"
    finally:
        db.close()


def test_notify_respects_muted_preference(client):
    """notify() should skip creating a notification when the user muted that type."""
    from utils.notifications import notify
    from tests.conftest import TestSession

    db = TestSession()
    try:
        db.add(NotificationPreference(username="testuser", notif_type="quality_done", enabled=0))
        db.commit()

        with patch("utils.ws_manager._push_via_main_loop"):
            notify(db, "testuser", "quality_done", "Should be muted")
        db.commit()

        count = db.query(Notification).count()
        assert count == 0, "Notification should not be created for muted type"
    finally:
        db.close()


def test_notify_ignores_mute_for_role_targeted(client):
    """Role-targeted notifications should not check individual user preferences."""
    from utils.notifications import notify
    from tests.conftest import TestSession

    db = TestSession()
    try:
        db.add(NotificationPreference(username="testuser", notif_type="access_request", enabled=0))
        db.commit()

        with patch("utils.ws_manager._push_via_main_loop"):
            notify(db, "testuser", "access_request", "New request", target_role="admin")
        db.commit()

        count = db.query(Notification).count()
        assert count == 1
    finally:
        db.close()


def test_notify_calls_push(client):
    """notify() should call _push_via_main_loop with correct data."""
    from utils.notifications import notify
    from tests.conftest import TestSession

    db = TestSession()
    try:
        with patch("utils.ws_manager._push_via_main_loop") as mock_push:
            notify(db, "alice", "cohort_shared", "Shared with you", item_id="cohort_42")
        db.commit()

        mock_push.assert_called_once()
        args = mock_push.call_args
        assert args[0][0] == "alice"
        data = args[0][1]
        assert data["type"] == "cohort_shared"
        assert data["title"] == "Shared with you"
        assert data["item_id"] == "cohort_42"
        assert data["read"] is False
    finally:
        db.close()


def test_notify_with_target_role_pushes_to_role(client):
    """When target_role is set, _push_via_main_loop should receive the role."""
    from utils.notifications import notify
    from tests.conftest import TestSession

    db = TestSession()
    try:
        with patch("utils.ws_manager._push_via_main_loop") as mock_push:
            notify(db, "alice", "access_request", "Request", target_role="admin")
        db.commit()

        mock_push.assert_called_once()
        assert mock_push.call_args[0][2] == "admin"
    finally:
        db.close()
