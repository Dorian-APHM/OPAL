"""
WebSocket connection manager for real-time notifications.

Maintains a mapping of username → set of active WebSocket connections.
When a notification is created, it is pushed instantly to all connected
clients of the target user (and optionally to all users with a target role).
"""
import asyncio
import json
import logging
from collections import defaultdict
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Thread-safe WebSocket connection manager."""

    def __init__(self):
        # username → set of WebSocket connections
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        # role → set of usernames (for role-based broadcasting)
        self._user_roles: dict[str, set[str]] = defaultdict(set)

    async def connect(self, websocket: WebSocket, username: str, roles: list[str] | None = None):
        await websocket.accept()
        self._connections[username].add(websocket)
        if roles:
            for role in roles:
                self._user_roles[role].add(username)
        logger.info("WS connected: %s (roles=%s, total=%d)", username, roles, self._count_total())

    def disconnect(self, websocket: WebSocket, username: str):
        conns = self._connections.get(username)
        if conns:
            conns.discard(websocket)
            if not conns:
                del self._connections[username]
                # Clean up role mappings
                for role_users in self._user_roles.values():
                    role_users.discard(username)
        logger.info("WS disconnected: %s (total=%d)", username, self._count_total())

    async def send_to_user(self, username: str, data: dict):
        """Send a message to all connections of a specific user."""
        conns = self._connections.get(username)
        if not conns:
            return
        message = json.dumps(data)
        dead = []
        for ws in conns:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            conns.discard(ws)

    async def send_to_role(self, role: str, data: dict):
        """Send a message to all users with a specific role."""
        usernames = self._user_roles.get(role, set())
        for username in list(usernames):
            await self.send_to_user(username, data)

    async def broadcast(self, data: dict):
        """Send a message to all connected users."""
        for username in list(self._connections.keys()):
            await self.send_to_user(username, data)

    def _count_total(self) -> int:
        return sum(len(conns) for conns in self._connections.values())


# Singleton instance
manager = ConnectionManager()


def push_notification_sync(username: str, notif_data: dict, target_role: str = ""):
    """Push a notification from synchronous code (e.g., inside a request handler).

    Schedules the coroutine on the running event loop. If no loop is running
    (e.g., background thread), the push is silently skipped — the client will
    pick it up on the next badge poll.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No event loop in this thread (e.g., background analysis thread).
        # Try to get the main loop if available.
        loop = None

    if loop and loop.is_running():
        async def _push():
            await manager.send_to_user(username, {"type": "notification", "data": notif_data})
            if target_role:
                await manager.send_to_role(target_role, {"type": "notification", "data": notif_data})

        loop.create_task(_push())
    else:
        # Fallback: try to push from a new thread-safe call
        try:
            import concurrent.futures
            _push_via_main_loop(username, notif_data, target_role)
        except Exception:
            pass  # Client will pick up via polling fallback


# Reference to the main event loop, set at startup
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop):
    global _main_loop
    _main_loop = loop


def _push_via_main_loop(username: str, notif_data: dict, target_role: str = ""):
    """Push notification from a background thread using the main event loop."""
    if _main_loop is None or _main_loop.is_closed():
        return

    async def _push():
        await manager.send_to_user(username, {"type": "notification", "data": notif_data})
        if target_role:
            await manager.send_to_role(target_role, {"type": "notification", "data": notif_data})

    asyncio.run_coroutine_threadsafe(_push(), _main_loop)
