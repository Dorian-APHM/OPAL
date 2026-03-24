# WebSocket Notifications — Architecture & Guide

## Overview

OPAL uses WebSocket connections for real-time notification delivery. When an action occurs (quality analysis completes, cohort shared, access granted, etc.), the backend pushes a notification instantly to all connected browser tabs of the target user, without polling.

## Architecture

```
┌──────────────┐     POST /api/auth/sse-ticket    ┌──────────────────┐
│   Frontend   │ ─────────────────────────────────→│   Backend        │
│  (React)     │     { ticket: "abc123" }          │   (FastAPI)      │
│              │ ←─────────────────────────────────│                  │
│              │                                   │                  │
│              │  ws://host/api/ws/notifications    │                  │
│              │       ?ticket=abc123              │                  │
│              │ ═════════════════════════════════→│  WebSocket       │
│              │          (upgrade)                │  endpoint        │
│              │ ←════════════════════════════════ │  (main.py)       │
│              │        ping / pong                │                  │
│              │  { type: "notification", data: {}}│                  │
│              │ ←════════════════════════════════ │  ConnectionMgr   │
└──────────────┘                                   │  (ws_manager.py) │
       │                                           └────────┬─────────┘
       │                                                    │
       │  Nginx reverse proxy                               │
       │  (WebSocket upgrade)                    notify() called from
       │                                         any router module
       ▼
┌──────────────┐
│    Nginx     │
│  /api/ws/    │  ← Dedicated location block
│              │    with HTTP/1.1 + Upgrade
└──────────────┘
```

## Data Flow

1. **User action** triggers a backend operation (e.g., share a cohort)
2. **Router** calls `notify(db, username, type, title, ...)` from `utils/notifications.py`
3. **`notify()`** creates a `Notification` row in the database
4. **`notify()`** calls `_push_via_main_loop()` to push via WebSocket
5. **`ConnectionManager`** sends `{"type": "notification", "data": {...}}` to all WS connections of the target user (and/or role)
6. **Frontend hook** (`useNotificationWs`) receives the message
7. **Custom events** dispatched: `opal:notification` + `opal:badges-refresh`
8. **UI updates**: NotificationCenter drawer + TopNav badge counts refresh

## Authentication

WebSocket connections use a **one-time ticket** mechanism (not bearer tokens):

1. Frontend calls `POST /api/auth/sse-ticket` with the regular JWT token
2. Backend generates a random ticket with 30-second TTL (max 1000 concurrent tickets)
3. Frontend opens WebSocket: `ws://host/api/ws/notifications?ticket=<ticket>`
4. Backend redeems the ticket (one-time use) and extracts username + roles
5. On invalid/expired ticket: connection closed with code `4001`

**Why tickets instead of JWT in headers?**
The browser WebSocket API does not support custom headers. Query parameters are the standard approach, but passing long-lived JWTs in URLs is a security risk (logged in access logs, referrer headers, etc.). One-time tickets with short TTL mitigate this.

## Keepalive Protocol

- Client sends `"ping"` every 30 seconds
- Server responds with `{"type": "pong"}`
- Non-ping messages are silently ignored
- If the connection drops, the client reconnects with exponential backoff: `[1s, 2s, 4s, 8s, 15s]`

## Nginx WebSocket Proxying — Lessons Learned

### The Problem

The initial deployment had WebSocket connections failing silently. The browser showed `WebSocket connection to 'ws://...' failed` with no useful error. The root cause was that the default Nginx `proxy_pass` configuration does **not** support WebSocket.

### Why WebSocket Needs Special Nginx Configuration

WebSocket uses the HTTP Upgrade mechanism (RFC 6455):

1. Client sends an HTTP request with `Upgrade: websocket` and `Connection: Upgrade` headers
2. Server responds with `101 Switching Protocols`
3. The connection is "upgraded" from HTTP to a persistent bidirectional TCP connection

By default, Nginx:
- Uses HTTP/1.0 for upstream connections (WebSocket requires HTTP/1.1)
- Does not forward `Upgrade` and `Connection` headers (they are hop-by-hop headers)
- Has a `proxy_read_timeout` of 60 seconds (kills idle WS connections)

### The Fix — Dedicated Location Block

```nginx
# frontend/nginx.conf

# CRITICAL: This block MUST appear BEFORE the generic /api/ block.
# Nginx matches locations by specificity — /api/ws/ is more specific
# than /api/ so it takes priority.
location /api/ws/ {
    proxy_pass http://opal-backend:8000;

    # 1. HTTP/1.1 is REQUIRED for WebSocket upgrade
    proxy_http_version 1.1;

    # 2. Forward the Upgrade and Connection headers
    #    Without these, Nginx strips them and the backend never sees
    #    the WebSocket handshake.
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";

    # 3. Standard proxy headers
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # 4. Timeouts — WebSocket connections are long-lived
    #    Default proxy_read_timeout is 60s which kills idle connections.
    #    86400s = 24 hours. The client keepalive ping every 30s ensures
    #    the connection is never truly idle.
    proxy_connect_timeout 10s;
    proxy_read_timeout 86400s;
    proxy_send_timeout 86400s;
}
```

### Common Pitfalls

| Issue | Symptom | Fix |
|-------|---------|-----|
| Missing `proxy_http_version 1.1` | `400 Bad Request` or silent failure | Add `proxy_http_version 1.1;` |
| Missing `Upgrade` / `Connection` headers | `200 OK` instead of `101 Switching Protocols` | Add `proxy_set_header Upgrade $http_upgrade;` and `proxy_set_header Connection "upgrade";` |
| Low `proxy_read_timeout` (default 60s) | WS disconnects after 60s of no data | Set to `86400s` (24h) + use client-side ping keepalive |
| `/api/ws/` block placed after `/api/` | Generic `/api/` block handles WS requests without upgrade | Place `/api/ws/` block BEFORE `/api/` |
| `proxy_buffering on` (default) | Can cause delays or issues with streaming | Not critical for WS (only affects HTTP), but disable for SSE endpoints |
| CSP `connect-src` missing `ws:` / `wss:` | Browser blocks WebSocket connection | Add `connect-src 'self' ws: wss:` to CSP header |

### CSP (Content Security Policy)

The CSP header must allow WebSocket connections:

```nginx
add_header Content-Security-Policy "... connect-src 'self' ws: wss:; ..." always;
```

Without `ws:` and `wss:` in `connect-src`, the browser blocks the WebSocket connection at the CSP level, before the HTTP request is even sent.

### Debugging WebSocket Issues

1. **Browser DevTools → Network → WS tab**: Shows the handshake request/response and all frames
2. **Check the HTTP response code**: Should be `101 Switching Protocols`, not `200` or `400`
3. **Check response headers**: Must contain `Upgrade: websocket` and `Connection: Upgrade`
4. **Nginx error log**: `docker compose logs opal-frontend | grep -i upgrade`
5. **Backend log**: Look for `WS connected:` / `WS disconnected:` messages
6. **Test without Nginx**: Connect directly to `ws://localhost:8000/api/ws/notifications` to isolate

### SSL/TLS (Production)

In production with HTTPS, WebSocket uses `wss://` (WebSocket Secure). The frontend hook auto-detects the protocol:

```typescript
const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
```

Nginx SSL termination works transparently — the `proxy_pass` to the backend remains plain HTTP, while the client-facing connection is encrypted.

## Backend Components

### `utils/ws_manager.py` — ConnectionManager

Singleton that tracks all active WebSocket connections:

- `_connections: dict[str, set[WebSocket]]` — username → active connections
- `_user_roles: dict[str, set[str]]` — role → usernames with that role
- `MAX_CONNECTIONS_PER_USER = 5` — limite de connexions WebSocket par utilisateur (éviction FIFO des plus anciennes)
- `connect(ws, username, roles)` — accept + track (évince la connexion la plus ancienne si limite atteinte)
- `disconnect(ws, username)` — remove + cleanup roles
- `send_to_user(username, data)` — push to specific user (all tabs)
- `send_to_role(role, data)` — broadcast to all users with a role
- `broadcast(data)` — push to everyone

Dead connections are automatically cleaned up on failed sends.

### Sync-to-Async Bridge

Most notification creation happens in synchronous request handlers. The `_push_via_main_loop()` function bridges sync→async:

```python
# Captured at startup
_main_loop: asyncio.AbstractEventLoop | None = None

def _push_via_main_loop(username, notif_data, target_role=""):
    """Push from sync code using the main event loop."""
    if _main_loop is None or _main_loop.is_closed():
        return  # Client will pick up via polling
    asyncio.run_coroutine_threadsafe(_push(), _main_loop)
```

If `push_notification_sync()` is called from a thread with a running event loop (e.g., the main FastAPI thread), it uses `loop.create_task()` directly. If called from a background thread (e.g., quality analysis), it falls back to `_push_via_main_loop()`.

### `utils/notifications.py` — notify() helper

Single function used across all 18+ router modules:

```python
notify(db, username, notif_type, title, message="", link="", target_role="", item_id="")
```

- Creates a `Notification` DB row via `db.flush()` (fait partie de la transaction de l'appelant, pas de `db.commit()` séparé)
- Respects user notification preferences (skips if muted)
- Role-targeted notifications bypass individual preferences
- Pushes via WebSocket in real time

### WebSocket Endpoint (`main.py`)

```
@app.websocket("/api/ws/notifications")
```

Located in `main.py` (not in a router) because FastAPI WebSocket endpoints must be registered on the app directly to work correctly with the ASGI lifecycle.

## Frontend Components

### `useNotificationWs(enabled)` Hook

Located in `frontend/src/hooks/useNotificationWs.ts`:

- Gets a one-time ticket via REST
- Opens WebSocket with exponential backoff reconnection
- Sends ping every 30s for keepalive
- Dispatches `opal:notification` custom event on received notifications
- Dispatches `opal:badges-refresh` to sync sidebar badges
- Falls back to polling if WebSocket unavailable

### Event-Driven UI Updates

The notification system uses custom DOM events for decoupled communication:

```
WebSocket message received
    → window.dispatchEvent(new CustomEvent('opal:notification', { detail: data }))
    → window.dispatchEvent(new Event('opal:badges-refresh'))

NotificationCenter listens to 'opal:notification' → updates drawer
TopNav listens to 'opal:badges-refresh' → calls GET /api/notifications/badges
Sidebar updates badge counts per tab
```

## Notification Types

| Type | Tab | Description |
|------|-----|-------------|
| `mapping_review` | mapping | New mapping suggestions to review |
| `mapping_applied` | mapping | Mapping decisions applied to CDM |
| `quality_done` | quality | Quality analysis completed |
| `cohort_shared` | cohorts | Cohort shared with user |
| `cohort_deleted` | cohorts | Shared cohort deleted |
| `cohort_updated` | cohorts | Shared cohort updated |
| `access_request` | users | User requested CDM access |
| `access_granted` | cdm | CDM access granted to user |
| `access_revoked` | cdm | CDM access revoked |
| `cdm_created` | cdm | New CDM registered |
| `cdm_updated` | cdm | CDM configuration updated |
| `cdm_deleted` | cdm | CDM deleted |
| `extraction_done` | data | Data extraction completed |
| `group_added` | — | User added to group (no badge) |
| `group_removed` | users | User removed from group |

## Testing

Tests are in `backend/tests/`:

- **`test_ws_manager.py`** — Unit tests for ConnectionManager (connect, disconnect, send, roles, dead connections)
- **`test_ws_endpoint.py`** — Integration tests for the WebSocket endpoint (auth, ping/pong, lifecycle, push delivery, role targeting)
- **`test_notifications.py`** — REST endpoint tests (CRUD, badges, filters)
- **`test_notification_preferences.py`** — Preferences API + `notify()` helper
- **`test_ws_nginx.py`** — Nginx configuration validation (WebSocket headers, timeouts, CSP, location ordering)

Run all notification-related tests:

```bash
cd backend
pytest tests/test_ws_manager.py tests/test_ws_endpoint.py tests/test_notifications.py tests/test_notification_preferences.py tests/test_ws_nginx.py -v
```
