"""
WebSocket connection manager for real-time notifications.

Maintains a mapping of username → set of active WebSocket connections.
When a notification is created, it is pushed instantly to all connected
clients of the target user (and optionally to all users with a target role).
"""
import asyncio
import json
import logging
import threading
from collections import defaultdict
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Thread-safe WebSocket connection manager.

    All mutations of the shared connection/role maps are protected by a lock.
    The lock is only ever held for short, synchronous critical sections — never
    across an ``await`` (network I/O) — so it cannot block the event loop or
    deadlock. Iterations always operate on snapshots taken under the lock, which
    prevents "set changed size during iteration" when coroutines interleave at
    await points or when a background thread schedules a push.
    """

    MAX_CONNECTIONS_PER_USER = 5

    def __init__(self):
        # username → set of WebSocket connections
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        # role → set of usernames (for role-based broadcasting)
        self._user_roles: dict[str, set[str]] = defaultdict(set)
        self._lock = threading.Lock()

    async def connect(self, websocket: WebSocket, username: str, roles: list[str] | None = None):
        # Decide on eviction under the lock, but await the close() outside it.
        with self._lock:
            existing = self._connections.get(username)
            evict = None
            if existing and len(existing) >= self.MAX_CONNECTIONS_PER_USER:
                # Evict an arbitrary existing connection (sets are unordered).
                evict = next(iter(existing))
                existing.discard(evict)
        if evict is not None:
            try:
                await evict.close(code=1008, reason="Too many connections")
            except Exception:
                pass
            logger.warning("WS evicted a connection for %s (limit=%d)", username, self.MAX_CONNECTIONS_PER_USER)

        await websocket.accept()
        with self._lock:
            self._connections[username].add(websocket)
            if roles:
                for role in roles:
                    self._user_roles[role].add(username)
            total = self._count_total_locked()
        logger.info("WS connected: %s (roles=%s, total=%d)", username, roles, total)

    def disconnect(self, websocket: WebSocket, username: str):
        with self._lock:
            conns = self._connections.get(username)
            if conns:
                conns.discard(websocket)
                if not conns:
                    del self._connections[username]
                    empty_roles = []
                    for role, role_users in self._user_roles.items():
                        role_users.discard(username)
                        if not role_users:
                            empty_roles.append(role)
                    for role in empty_roles:
                        del self._user_roles[role]
            total = self._count_total_locked()
        logger.info("WS disconnected: %s (total=%d)", username, total)

    async def send_to_user(self, username: str, data: dict):
        """Send a message to all connections of a specific user."""
        with self._lock:
            conns = self._connections.get(username)
            targets = list(conns) if conns else []
        if not targets:
            return
        message = json.dumps(data)
        dead = []
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                logger.debug("WebSocket send failed for %s, marking connection dead", username)
                dead.append(ws)
        if dead:
            with self._lock:
                conns = self._connections.get(username)
                if conns:
                    for ws in dead:
                        conns.discard(ws)
                    if not conns:
                        del self._connections[username]

    async def send_to_role(self, role: str, data: dict):
        """Send a message to all users with a specific role."""
        with self._lock:
            usernames = list(self._user_roles.get(role, set()))
        for username in usernames:
            await self.send_to_user(username, data)

    async def broadcast(self, data: dict):
        """Send a message to all connected users."""
        with self._lock:
            usernames = list(self._connections.keys())
        for username in usernames:
            await self.send_to_user(username, data)

    def _count_total_locked(self) -> int:
        return sum(len(conns) for conns in self._connections.values())

    def _count_total(self) -> int:
        with self._lock:
            return self._count_total_locked()


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
        # Fallback: schedule onto the main loop from this background thread.
        try:
            _push_via_main_loop(username, notif_data, target_role)
        except Exception:
            logger.debug("WS push fallback failed for %s, client will poll", username)


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
