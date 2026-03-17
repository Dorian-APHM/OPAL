"""Tests for WebSocket connection manager (utils/ws_manager.py)."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from utils.ws_manager import ConnectionManager


@pytest.fixture
def mgr():
    return ConnectionManager()


@pytest.fixture
def make_ws():
    """Create a mock WebSocket that records sent messages."""
    def _make():
        ws = AsyncMock()
        ws.sent = []
        async def _send_text(msg):
            ws.sent.append(msg)
        ws.send_text = AsyncMock(side_effect=_send_text)
        return ws
    return _make


# ── connect / disconnect ──

@pytest.mark.asyncio
async def test_connect_accepts_and_tracks(mgr, make_ws):
    ws = make_ws()
    await mgr.connect(ws, "alice")
    ws.accept.assert_awaited_once()
    assert mgr._count_total() == 1


@pytest.mark.asyncio
async def test_connect_multiple_per_user(mgr, make_ws):
    ws1, ws2 = make_ws(), make_ws()
    await mgr.connect(ws1, "alice")
    await mgr.connect(ws2, "alice")
    assert mgr._count_total() == 2
    assert len(mgr._connections["alice"]) == 2


@pytest.mark.asyncio
async def test_disconnect_removes_connection(mgr, make_ws):
    ws = make_ws()
    await mgr.connect(ws, "alice")
    mgr.disconnect(ws, "alice")
    assert mgr._count_total() == 0
    assert "alice" not in mgr._connections


@pytest.mark.asyncio
async def test_disconnect_partial(mgr, make_ws):
    ws1, ws2 = make_ws(), make_ws()
    await mgr.connect(ws1, "alice")
    await mgr.connect(ws2, "alice")
    mgr.disconnect(ws1, "alice")
    assert mgr._count_total() == 1
    assert ws2 in mgr._connections["alice"]


@pytest.mark.asyncio
async def test_disconnect_cleans_roles(mgr, make_ws):
    ws = make_ws()
    await mgr.connect(ws, "alice", roles=["admin"])
    assert "alice" in mgr._user_roles["admin"]
    mgr.disconnect(ws, "alice")
    assert "alice" not in mgr._user_roles.get("admin", set())


@pytest.mark.asyncio
async def test_disconnect_unknown_user_noop(mgr, make_ws):
    """Disconnecting a user that was never connected should not crash."""
    ws = make_ws()
    mgr.disconnect(ws, "nobody")  # should not raise


# ── send_to_user ──

@pytest.mark.asyncio
async def test_send_to_user(mgr, make_ws):
    ws = make_ws()
    await mgr.connect(ws, "alice")
    await mgr.send_to_user("alice", {"type": "test", "msg": "hi"})
    assert len(ws.sent) == 1
    assert json.loads(ws.sent[0]) == {"type": "test", "msg": "hi"}


@pytest.mark.asyncio
async def test_send_to_user_multiple_connections(mgr, make_ws):
    ws1, ws2 = make_ws(), make_ws()
    await mgr.connect(ws1, "alice")
    await mgr.connect(ws2, "alice")
    await mgr.send_to_user("alice", {"x": 1})
    assert len(ws1.sent) == 1
    assert len(ws2.sent) == 1


@pytest.mark.asyncio
async def test_send_to_user_no_connections(mgr):
    """Sending to a user with no connections should not raise."""
    await mgr.send_to_user("nobody", {"type": "test"})


@pytest.mark.asyncio
async def test_send_to_user_removes_dead_connections(mgr, make_ws):
    ws_good = make_ws()
    ws_dead = make_ws()
    ws_dead.send_text = AsyncMock(side_effect=RuntimeError("connection closed"))

    await mgr.connect(ws_good, "alice")
    await mgr.connect(ws_dead, "alice")

    await mgr.send_to_user("alice", {"type": "test"})
    # Dead connection should have been removed
    assert ws_dead not in mgr._connections["alice"]
    assert ws_good in mgr._connections["alice"]


# ── send_to_role ──

@pytest.mark.asyncio
async def test_send_to_role(mgr, make_ws):
    ws_alice = make_ws()
    ws_bob = make_ws()
    ws_carol = make_ws()
    await mgr.connect(ws_alice, "alice", roles=["admin"])
    await mgr.connect(ws_bob, "bob", roles=["admin"])
    await mgr.connect(ws_carol, "carol", roles=["viewer"])

    await mgr.send_to_role("admin", {"type": "admin_msg"})
    assert len(ws_alice.sent) == 1
    assert len(ws_bob.sent) == 1
    assert len(ws_carol.sent) == 0


@pytest.mark.asyncio
async def test_send_to_role_unknown(mgr):
    """Sending to a non-existent role should not raise."""
    await mgr.send_to_role("nonexistent", {"type": "test"})


# ── broadcast ──

@pytest.mark.asyncio
async def test_broadcast(mgr, make_ws):
    ws_alice = make_ws()
    ws_bob = make_ws()
    await mgr.connect(ws_alice, "alice")
    await mgr.connect(ws_bob, "bob")

    await mgr.broadcast({"type": "global"})
    assert len(ws_alice.sent) == 1
    assert len(ws_bob.sent) == 1


# ── role tracking ──

@pytest.mark.asyncio
async def test_multiple_roles(mgr, make_ws):
    ws = make_ws()
    await mgr.connect(ws, "alice", roles=["admin", "data-manager"])
    assert "alice" in mgr._user_roles["admin"]
    assert "alice" in mgr._user_roles["data-manager"]


@pytest.mark.asyncio
async def test_connect_without_roles(mgr, make_ws):
    ws = make_ws()
    await mgr.connect(ws, "alice", roles=None)
    assert mgr._count_total() == 1
    # No role entries
    for role_users in mgr._user_roles.values():
        assert "alice" not in role_users
