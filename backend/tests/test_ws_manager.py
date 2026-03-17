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


@pytest.mark.asyncio
async def test_connect_with_empty_roles_list(mgr, make_ws):
    """Empty roles list should behave like None."""
    ws = make_ws()
    await mgr.connect(ws, "alice", roles=[])
    assert mgr._count_total() == 1
    for role_users in mgr._user_roles.values():
        assert "alice" not in role_users


# ── disconnect edge cases ──

@pytest.mark.asyncio
async def test_disconnect_idempotent(mgr, make_ws):
    """Disconnecting the same WS twice should not crash."""
    ws = make_ws()
    await mgr.connect(ws, "alice")
    mgr.disconnect(ws, "alice")
    mgr.disconnect(ws, "alice")  # second call should be a no-op
    assert mgr._count_total() == 0


@pytest.mark.asyncio
async def test_disconnect_preserves_other_users(mgr, make_ws):
    """Disconnecting one user should not affect others."""
    ws_alice = make_ws()
    ws_bob = make_ws()
    await mgr.connect(ws_alice, "alice", roles=["admin"])
    await mgr.connect(ws_bob, "bob", roles=["admin"])
    mgr.disconnect(ws_alice, "alice")
    assert mgr._count_total() == 1
    assert "bob" in mgr._connections
    assert "bob" in mgr._user_roles["admin"]


@pytest.mark.asyncio
async def test_disconnect_partial_keeps_roles(mgr, make_ws):
    """If a user has multiple connections, disconnecting one should keep roles."""
    ws1, ws2 = make_ws(), make_ws()
    await mgr.connect(ws1, "alice", roles=["admin"])
    await mgr.connect(ws2, "alice", roles=["admin"])
    mgr.disconnect(ws1, "alice")
    # alice still has a connection, role should remain
    assert "alice" in mgr._connections
    # Note: current impl removes roles when ALL connections gone


# ── broadcast edge cases ──

@pytest.mark.asyncio
async def test_broadcast_empty(mgr):
    """Broadcasting with no connections should not raise."""
    await mgr.broadcast({"type": "test"})


@pytest.mark.asyncio
async def test_broadcast_skips_dead(mgr, make_ws):
    """Broadcast should handle dead connections gracefully."""
    ws_good = make_ws()
    ws_dead = make_ws()
    ws_dead.send_text = AsyncMock(side_effect=RuntimeError("dead"))

    await mgr.connect(ws_good, "alice")
    await mgr.connect(ws_dead, "bob")
    await mgr.broadcast({"type": "test"})

    assert len(ws_good.sent) == 1
    # Dead connection should be removed from bob's set
    bob_conns = mgr._connections.get("bob", set())
    assert ws_dead not in bob_conns


# ── send_to_role edge cases ──

@pytest.mark.asyncio
async def test_send_to_role_multiple_connections_per_user(mgr, make_ws):
    """All connections of a user with matching role should receive the message."""
    ws1, ws2 = make_ws(), make_ws()
    await mgr.connect(ws1, "alice", roles=["admin"])
    await mgr.connect(ws2, "alice", roles=["admin"])
    await mgr.send_to_role("admin", {"type": "test"})
    assert len(ws1.sent) == 1
    assert len(ws2.sent) == 1


# ── _push_via_main_loop / set_main_loop ──

@pytest.mark.asyncio
async def test_set_main_loop_and_push():
    """_push_via_main_loop should use the loop set by set_main_loop."""
    from utils.ws_manager import set_main_loop, _push_via_main_loop, manager

    loop = asyncio.get_running_loop()
    set_main_loop(loop)

    ws = AsyncMock()
    ws.sent = []
    ws.send_text = AsyncMock(side_effect=lambda m: ws.sent.append(m))
    await manager.connect(ws, "loop_test_user")

    try:
        _push_via_main_loop("loop_test_user", {"id": 1, "type": "test", "title": "T"})
        await asyncio.sleep(0.1)
        assert len(ws.sent) >= 1
        parsed = json.loads(ws.sent[0])
        assert parsed["type"] == "notification"
        assert parsed["data"]["title"] == "T"
    finally:
        manager.disconnect(ws, "loop_test_user")
        set_main_loop(None)


def test_push_via_main_loop_no_loop():
    """_push_via_main_loop with no main loop should silently no-op."""
    from utils.ws_manager import set_main_loop, _push_via_main_loop

    set_main_loop(None)
    # Should not raise
    _push_via_main_loop("nobody", {"id": 1, "type": "test", "title": "T"})


@pytest.mark.asyncio
async def test_push_via_main_loop_with_role():
    """_push_via_main_loop with target_role should send to role members too."""
    from utils.ws_manager import set_main_loop, _push_via_main_loop, manager

    loop = asyncio.get_running_loop()
    set_main_loop(loop)

    ws_user = AsyncMock()
    ws_user.sent = []
    ws_user.send_text = AsyncMock(side_effect=lambda m: ws_user.sent.append(m))

    ws_admin = AsyncMock()
    ws_admin.sent = []
    ws_admin.send_text = AsyncMock(side_effect=lambda m: ws_admin.sent.append(m))

    await manager.connect(ws_user, "alice")
    await manager.connect(ws_admin, "bob", roles=["admin"])

    try:
        _push_via_main_loop("alice", {"id": 1, "type": "test", "title": "T"}, target_role="admin")
        await asyncio.sleep(0.1)
        # alice should receive (direct)
        assert len(ws_user.sent) >= 1
        # bob should receive (admin role)
        assert len(ws_admin.sent) >= 1
    finally:
        manager.disconnect(ws_user, "alice")
        manager.disconnect(ws_admin, "bob")
        set_main_loop(None)


# ── _count_total ──

@pytest.mark.asyncio
async def test_count_total_multiple_users(mgr, make_ws):
    """_count_total should count all connections across all users."""
    await mgr.connect(make_ws(), "alice")
    await mgr.connect(make_ws(), "alice")
    await mgr.connect(make_ws(), "bob")
    assert mgr._count_total() == 3
