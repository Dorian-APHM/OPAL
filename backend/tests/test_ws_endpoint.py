"""Tests for the WebSocket notification endpoint in main.py.

These tests verify:
1. Ticket-based authentication (accept/reject)
2. Ping/pong keepalive
3. Connection lifecycle (connect → disconnect → cleanup)
4. Real-time push: notification created via REST → delivered via WS
5. push_notification_sync helper
6. Role-based targeting via WS
7. Multiple concurrent WS clients
"""
import asyncio
import json
import threading
import time
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from utils.ws_manager import ConnectionManager, manager as global_manager


# ── Helpers ──

def _ws_connect(client, username="testuser", roles=None):
    """Context manager that connects a WS with a mocked valid ticket."""
    user_info = {"preferred_username": username, "roles": roles or []}
    return patch("auth.keycloak._redeem_sse_ticket", return_value=user_info)


# ── Authentication ──

def test_ws_rejects_without_ticket(client):
    """WebSocket connection without a ticket should be rejected with 4001."""
    with patch("auth.keycloak._redeem_sse_ticket", return_value=None):
        with pytest.raises(Exception):
            with client.websocket_connect("/api/ws/notifications?ticket="):
                pass


def test_ws_rejects_invalid_ticket(client):
    """WebSocket connection with an invalid ticket should be rejected."""
    with patch("auth.keycloak._redeem_sse_ticket", return_value=None):
        with pytest.raises(Exception):
            with client.websocket_connect("/api/ws/notifications?ticket=bad_ticket"):
                pass


def test_ws_rejects_empty_no_ticket_param(client):
    """WebSocket without ?ticket param at all should be rejected (empty string default)."""
    with patch("auth.keycloak._redeem_sse_ticket", return_value=None):
        with pytest.raises(Exception):
            with client.websocket_connect("/api/ws/notifications"):
                pass


def test_ws_accepts_valid_ticket(client):
    """WebSocket connection with a valid ticket should be accepted."""
    user_info = {"preferred_username": "alice", "roles": ["admin"]}
    with patch("auth.keycloak._redeem_sse_ticket", return_value=user_info) as mock_redeem:
        with client.websocket_connect("/api/ws/notifications?ticket=valid_ticket") as ws:
            ws.send_text("ping")
            resp = ws.receive_text()
            assert resp == '{"type":"pong"}'
            mock_redeem.assert_called_once_with("valid_ticket")


def test_ws_ticket_is_consumed_once(client):
    """The ticket should be redeemed exactly once per connection."""
    call_count = 0
    def _redeem_once(ticket):
        nonlocal call_count
        call_count += 1
        return {"preferred_username": "alice", "roles": []}

    with patch("auth.keycloak._redeem_sse_ticket", side_effect=_redeem_once):
        with client.websocket_connect("/api/ws/notifications?ticket=one_time") as ws:
            ws.send_text("ping")
            ws.receive_text()

    assert call_count == 1


# ── Ping / Pong ──

def test_ws_ping_pong(client):
    """WebSocket should respond to ping with pong."""
    with _ws_connect(client, "bob"):
        with client.websocket_connect("/api/ws/notifications?ticket=t1") as ws:
            ws.send_text("ping")
            resp = ws.receive_text()
            assert resp == '{"type":"pong"}'


def test_ws_multiple_pings(client):
    """Multiple pings should each get a pong response."""
    with _ws_connect(client, "bob"):
        with client.websocket_connect("/api/ws/notifications?ticket=t1") as ws:
            for _ in range(3):
                ws.send_text("ping")
                resp = ws.receive_text()
                assert json.loads(resp)["type"] == "pong"


def test_ws_non_ping_message_ignored(client):
    """Non-ping messages should not generate a response (just discarded)."""
    with _ws_connect(client, "bob"):
        with client.websocket_connect("/api/ws/notifications?ticket=t1") as ws:
            ws.send_text("hello")
            # Send a ping after to confirm connection is still alive
            ws.send_text("ping")
            resp = ws.receive_text()
            assert json.loads(resp)["type"] == "pong"


# ── Connection lifecycle ──

def test_ws_disconnect_cleans_up(client):
    """After WebSocket disconnect, user should be removed from manager."""
    user_info = {"preferred_username": "cleanup_user", "roles": ["viewer"]}
    with patch("auth.keycloak._redeem_sse_ticket", return_value=user_info):
        with client.websocket_connect("/api/ws/notifications?ticket=t2") as ws:
            assert "cleanup_user" in global_manager._connections
            ws.send_text("ping")
            ws.receive_text()

    # After context exit (disconnect), user should be cleaned up
    assert "cleanup_user" not in global_manager._connections


def test_ws_user_tracked_in_manager(client):
    """While connected, the user should appear in the global manager."""
    with _ws_connect(client, "tracked_user", roles=["admin"]):
        with client.websocket_connect("/api/ws/notifications?ticket=t") as ws:
            assert "tracked_user" in global_manager._connections
            assert global_manager._count_total() >= 1
            ws.send_text("ping")
            ws.receive_text()


def test_ws_roles_registered_in_manager(client):
    """User roles should be registered in the manager on connect."""
    with _ws_connect(client, "role_user", roles=["admin", "data-manager"]):
        with client.websocket_connect("/api/ws/notifications?ticket=t") as ws:
            assert "role_user" in global_manager._user_roles.get("admin", set())
            assert "role_user" in global_manager._user_roles.get("data-manager", set())
            ws.send_text("ping")
            ws.receive_text()


# ── Real-time push: the critical tests that would have caught the WS bug ──

@pytest.mark.asyncio
async def test_manager_push_to_connected_user():
    """Simulates the core flow: user connects, notification pushed, user receives it.

    THIS is the test that would have caught a broken WS notification pipeline.
    """
    mgr = ConnectionManager()
    ws = AsyncMock()
    ws.sent = []
    async def _send(msg):
        ws.sent.append(msg)
    ws.send_text = AsyncMock(side_effect=_send)

    await mgr.connect(ws, "alice", roles=["admin"])

    # Simulate what notify() does: push notification data
    notif_data = {
        "id": 1, "type": "quality_done", "title": "Analysis complete",
        "message": "Done", "link": "/quality", "item_id": None,
        "read": False, "created_at": "2026-03-17T12:00:00",
    }
    await mgr.send_to_user("alice", {"type": "notification", "data": notif_data})

    assert len(ws.sent) == 1
    received = json.loads(ws.sent[0])
    assert received["type"] == "notification"
    assert received["data"]["title"] == "Analysis complete"
    assert received["data"]["type"] == "quality_done"


@pytest.mark.asyncio
async def test_manager_push_to_role():
    """Push to role should reach all users with that role.

    Would have caught bugs in role-based notification routing.
    """
    mgr = ConnectionManager()
    ws_admin1 = AsyncMock()
    ws_admin1.sent = []
    ws_admin1.send_text = AsyncMock(side_effect=lambda m: ws_admin1.sent.append(m))

    ws_admin2 = AsyncMock()
    ws_admin2.sent = []
    ws_admin2.send_text = AsyncMock(side_effect=lambda m: ws_admin2.sent.append(m))

    ws_viewer = AsyncMock()
    ws_viewer.sent = []
    ws_viewer.send_text = AsyncMock(side_effect=lambda m: ws_viewer.sent.append(m))

    await mgr.connect(ws_admin1, "alice", roles=["admin"])
    await mgr.connect(ws_admin2, "bob", roles=["admin"])
    await mgr.connect(ws_viewer, "carol", roles=["viewer"])

    await mgr.send_to_role("admin", {
        "type": "notification",
        "data": {"title": "New access request", "type": "access_request"},
    })

    assert len(ws_admin1.sent) == 1
    assert len(ws_admin2.sent) == 1
    assert len(ws_viewer.sent) == 0  # viewer should NOT receive admin notification


@pytest.mark.asyncio
async def test_push_notification_sync_with_running_loop():
    """push_notification_sync should schedule push on the running event loop.

    Would have caught issues with the sync→async bridge.
    """
    from utils.ws_manager import push_notification_sync, manager

    ws = AsyncMock()
    ws.sent = []
    ws.send_text = AsyncMock(side_effect=lambda m: ws.sent.append(m))
    await manager.connect(ws, "sync_test_user")

    try:
        push_notification_sync("sync_test_user", {
            "id": 99, "type": "cohort_shared", "title": "Shared!",
        })
        # Give the event loop a chance to execute the scheduled task
        await asyncio.sleep(0.1)

        assert len(ws.sent) >= 1
        received = json.loads(ws.sent[0])
        assert received["type"] == "notification"
        assert received["data"]["title"] == "Shared!"
    finally:
        manager.disconnect(ws, "sync_test_user")


@pytest.mark.asyncio
async def test_push_notification_sync_no_loop_does_not_crash():
    """push_notification_sync from a thread with no event loop should not crash."""
    from utils.ws_manager import push_notification_sync

    errors = []
    def _call_from_thread():
        try:
            push_notification_sync("nobody", {"id": 1, "type": "test", "title": "T"})
        except Exception as e:
            errors.append(e)

    t = threading.Thread(target=_call_from_thread)
    t.start()
    t.join(timeout=2)
    assert errors == [], f"push_notification_sync crashed in background thread: {errors}"


@pytest.mark.asyncio
async def test_notification_delivery_with_dead_ws():
    """If a WS connection dies, the message should still be sent to other connections.

    Would have caught the bug where one dead connection blocks all deliveries.
    """
    mgr = ConnectionManager()

    ws_good = AsyncMock()
    ws_good.sent = []
    ws_good.send_text = AsyncMock(side_effect=lambda m: ws_good.sent.append(m))

    ws_dead = AsyncMock()
    ws_dead.send_text = AsyncMock(side_effect=RuntimeError("connection reset"))

    await mgr.connect(ws_good, "alice")
    await mgr.connect(ws_dead, "alice")

    # Push should succeed for the good connection despite the dead one
    await mgr.send_to_user("alice", {"type": "notification", "data": {"title": "Test"}})

    assert len(ws_good.sent) == 1
    assert ws_dead not in mgr._connections["alice"]  # dead connection cleaned up


@pytest.mark.asyncio
async def test_notification_json_serialization():
    """Notification data should be correctly JSON-serialized over WS."""
    mgr = ConnectionManager()
    ws = AsyncMock()
    ws.sent = []
    ws.send_text = AsyncMock(side_effect=lambda m: ws.sent.append(m))
    await mgr.connect(ws, "alice")

    # Simulate a realistic notification payload
    await mgr.send_to_user("alice", {
        "type": "notification",
        "data": {
            "id": 42,
            "type": "mapping_review",
            "title": "Nouveau mapping à vérifier",
            "message": "5 suggestions pour Aspirin",
            "link": "/mapping?cdm=test&domain=Drug",
            "item_id": "Aspirin",
            "read": False,
            "created_at": "2026-03-17T14:30:00+00:00",
        },
    })

    raw = ws.sent[0]
    parsed = json.loads(raw)
    assert parsed["data"]["id"] == 42
    assert parsed["data"]["item_id"] == "Aspirin"
    assert "2026-03-17" in parsed["data"]["created_at"]


# ── Integration: REST create → WS delivery ──

def test_create_notification_triggers_ws_push(client):
    """Creating a notification via REST should trigger a WS push call.

    THIS is the end-to-end test that would have caught a missing or broken
    WS push after notification creation.
    """
    with patch("utils.ws_manager._push_via_main_loop") as mock_push:
        resp = client.post("/api/notifications/create", json={
            "username": "testuser",
            "type": "quality_done",
            "title": "Analysis done",
            "message": "Quality analysis for Drug completed",
            "link": "/quality",
            "item_id": "Drug",
        })
        assert resp.status_code == 200

        # Verify the WS push was called
        mock_push.assert_called_once()
        call_args = mock_push.call_args[0]
        assert call_args[0] == "testuser"  # username
        push_data = call_args[1]
        assert push_data["type"] == "quality_done"
        assert push_data["title"] == "Analysis done"
        assert push_data["item_id"] == "Drug"
        assert push_data["read"] is False


def test_create_notification_push_data_has_all_fields(client):
    """The WS push payload should contain all fields the frontend needs."""
    with patch("utils.ws_manager._push_via_main_loop") as mock_push:
        client.post("/api/notifications/create", json={
            "username": "testuser",
            "type": "cohort_shared",
            "title": "Cohort shared",
            "message": "Bob shared Diabetes cohort with you",
            "link": "/cohorts/5",
            "item_id": "5",
        })

        push_data = mock_push.call_args[0][1]
        required_fields = ["id", "type", "title", "message", "link", "item_id", "read", "created_at"]
        for field in required_fields:
            assert field in push_data, f"Missing field '{field}' in WS push payload"


def test_create_notification_non_admin_forbidden(client):
    """Non-admin users should not be able to create notifications via REST."""
    resp = client.post(
        "/api/notifications/create",
        json={"username": "testuser", "type": "test", "title": "T"},
        headers={"X-Test-Roles": "viewer"},
    )
    assert resp.status_code == 403
