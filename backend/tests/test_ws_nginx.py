"""Tests validating nginx.conf WebSocket configuration.

These tests parse the nginx.conf file and verify that all the directives
required for WebSocket proxying are present and correct. This prevents
regressions where a config change inadvertently breaks WebSocket support.

Background: The initial deployment had WebSocket failing silently because
nginx defaults (HTTP/1.0, no Upgrade header forwarding, 60s read timeout)
are incompatible with WebSocket connections.
"""
import re
import pytest

NGINX_CONF_PATH = "frontend/nginx.conf"


@pytest.fixture(scope="module")
def nginx_conf():
    """Read the nginx.conf file content."""
    import os
    conf_path = os.path.join(os.path.dirname(__file__), "..", "..", NGINX_CONF_PATH)
    with open(conf_path) as f:
        return f.read()


@pytest.fixture(scope="module")
def ws_block(nginx_conf):
    """Extract the /api/ws/ location block from nginx.conf."""
    # Match 'location /api/ws/ { ... }' block
    match = re.search(
        r'location\s+/api/ws/\s*\{([^}]+)\}',
        nginx_conf,
        re.DOTALL,
    )
    assert match, "Missing 'location /api/ws/' block in nginx.conf"
    return match.group(1)


# ── WebSocket location block existence ──

def test_ws_location_block_exists(ws_block):
    """nginx.conf must have a dedicated location block for /api/ws/."""
    assert ws_block is not None


# ── HTTP/1.1 (required for WebSocket upgrade) ──

def test_ws_proxy_http_version(ws_block):
    """WebSocket requires HTTP/1.1 for the Upgrade mechanism.

    Without this, nginx uses HTTP/1.0 upstream which does not support
    the Connection: Upgrade header, causing a 400 or silent failure.
    """
    assert "proxy_http_version 1.1" in ws_block, (
        "Missing 'proxy_http_version 1.1' — WebSocket upgrade requires HTTP/1.1"
    )


# ── Upgrade headers ──

def test_ws_upgrade_header(ws_block):
    """The Upgrade header must be forwarded to the backend.

    Without this, nginx strips the hop-by-hop Upgrade header and
    the backend never sees the WebSocket handshake request.
    """
    assert re.search(r'proxy_set_header\s+Upgrade\s+\$http_upgrade', ws_block), (
        "Missing 'proxy_set_header Upgrade $http_upgrade' — "
        "backend won't receive WebSocket upgrade request"
    )


def test_ws_connection_upgrade_header(ws_block):
    """The Connection header must be set to 'upgrade'.

    Without this, the backend receives Connection: keep-alive (default)
    instead of Connection: Upgrade, and responds with 200 instead of 101.
    """
    assert re.search(r'proxy_set_header\s+Connection\s+"upgrade"', ws_block), (
        "Missing 'proxy_set_header Connection \"upgrade\"' — "
        "backend will respond 200 instead of 101 Switching Protocols"
    )


# ── Timeouts ──

def test_ws_read_timeout_long_lived(ws_block):
    """proxy_read_timeout must be much longer than the default 60s.

    WebSocket connections are long-lived. The default 60s timeout
    kills idle connections, even with client-side keepalive pings.
    We require at least 3600s (1 hour).
    """
    match = re.search(r'proxy_read_timeout\s+(\d+)s', ws_block)
    assert match, "Missing proxy_read_timeout in WebSocket location block"
    timeout = int(match.group(1))
    assert timeout >= 3600, (
        f"proxy_read_timeout is {timeout}s — must be >= 3600s for WebSocket. "
        f"Default 60s kills idle connections."
    )


def test_ws_send_timeout_long_lived(ws_block):
    """proxy_send_timeout should match read_timeout for consistency."""
    match = re.search(r'proxy_send_timeout\s+(\d+)s', ws_block)
    assert match, "Missing proxy_send_timeout in WebSocket location block"
    timeout = int(match.group(1))
    assert timeout >= 3600, (
        f"proxy_send_timeout is {timeout}s — should be >= 3600s for WebSocket"
    )


def test_ws_connect_timeout_reasonable(ws_block):
    """proxy_connect_timeout should be short (connection establishment)."""
    match = re.search(r'proxy_connect_timeout\s+(\d+)s', ws_block)
    assert match, "Missing proxy_connect_timeout in WebSocket location block"
    timeout = int(match.group(1))
    assert timeout <= 30, (
        f"proxy_connect_timeout is {timeout}s — should be <= 30s"
    )


# ── Proxy pass ──

def test_ws_proxy_pass_to_backend(ws_block):
    """WebSocket traffic must be proxied to the backend service."""
    assert re.search(r'proxy_pass\s+http://opal-backend:8000', ws_block), (
        "WebSocket location should proxy_pass to http://opal-backend:8000"
    )


# ── Standard proxy headers ──

def test_ws_host_header(ws_block):
    """Host header should be forwarded for correct virtual host routing."""
    assert re.search(r'proxy_set_header\s+Host\s+\$host', ws_block)


def test_ws_real_ip_header(ws_block):
    """X-Real-IP should be forwarded for logging and rate limiting."""
    assert re.search(r'proxy_set_header\s+X-Real-IP\s+\$remote_addr', ws_block)


def test_ws_forwarded_for_header(ws_block):
    """X-Forwarded-For should be forwarded for proxy chain tracking."""
    assert re.search(r'proxy_set_header\s+X-Forwarded-For', ws_block)


def test_ws_forwarded_proto_header(ws_block):
    """X-Forwarded-Proto should be forwarded for correct ws/wss detection."""
    assert re.search(r'proxy_set_header\s+X-Forwarded-Proto\s+\$scheme', ws_block)


# ── CSP (Content Security Policy) ──

def test_csp_allows_websocket(nginx_conf):
    """CSP connect-src must include ws: and wss: for WebSocket connections.

    Without this, the browser blocks the WebSocket connection at the
    CSP level, before the HTTP upgrade request is even sent. The browser
    console shows 'Refused to connect' with no useful network trace.
    """
    csp_match = re.search(r'Content-Security-Policy\s+"([^"]+)"', nginx_conf)
    assert csp_match, "Missing Content-Security-Policy header in nginx.conf"
    csp = csp_match.group(1)

    connect_src = re.search(r'connect-src\s+([^;]+)', csp)
    assert connect_src, "Missing connect-src directive in CSP"
    connect_value = connect_src.group(1)
    assert "ws:" in connect_value, "CSP connect-src missing 'ws:' — blocks WebSocket"
    assert "wss:" in connect_value, "CSP connect-src missing 'wss:' — blocks secure WebSocket"


# ── Location block ordering ──

def test_ws_block_before_generic_api_block(nginx_conf):
    """/api/ws/ block must appear before the generic /api/ block in nginx.conf.

    Nginx matches location blocks by prefix specificity, so /api/ws/ (more
    specific) takes priority over /api/ regardless of order. However, keeping
    it before the generic /api/ block makes the intent explicit.
    """
    ws_pos = nginx_conf.find("location /api/ws/")
    # Find the generic /api/ block (not /api/ohdsi/ or /api/ws/)
    generic_api_pos = nginx_conf.find("location /api/ {")
    assert ws_pos != -1, "Missing 'location /api/ws/' block"
    assert generic_api_pos != -1, "Missing generic 'location /api/' block"
    assert ws_pos < generic_api_pos, (
        "/api/ws/ location block should appear before the generic /api/ block "
        "for clarity and to prevent confusion during reviews"
    )


# ── No buffering directives that could interfere ──

def test_ws_no_proxy_buffering_on(ws_block):
    """WebSocket block should not have proxy_buffering explicitly on.

    While proxy_buffering defaults to on and doesn't affect WebSocket
    (which uses raw TCP after upgrade), having it explicitly 'on' in
    the WS block suggests a misunderstanding and could mask issues.
    """
    # It's OK if proxy_buffering is absent (default), or 'off'
    buffering_match = re.search(r'proxy_buffering\s+on', ws_block)
    assert not buffering_match, (
        "proxy_buffering should not be explicitly 'on' in WebSocket block"
    )
