"""
Keycloak OIDC authentication middleware with role-based access control.
Validates JWT tokens locally using JWKS keys (no issuer hostname dependency).
Permissions are driven by permissions.yaml via auth.permissions module.

Uses a pure ASGI middleware (not BaseHTTPMiddleware) so that StreamingResponse
(SSE log endpoints) is never buffered — events are forwarded in real-time.
"""
import logging
import re
import threading
import time
import uuid

import jwt
from jwt import PyJWKClient
from fastapi import Request, HTTPException, Depends
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from config import AUTH_ENABLED, ENVIRONMENT, KEYCLOAK_URL, KEYCLOAK_REALM, KEYCLOAK_CLIENT_ID, KEYCLOAK_ISSUER_URL
from auth.permissions import check_route_access, has_any_full_visibility, get_role_names

logger = logging.getLogger(__name__)

# JWKS client for local JWT validation (caches keys automatically)
_jwks_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
_jwks_client = PyJWKClient(_jwks_url, cache_keys=True, lifespan=300)

# Public endpoints that don't require authentication
PUBLIC_PATHS = {"/api/health", "/api/i18n", "/api/access-requests", "/docs", "/openapi.json", "/redoc", "/"}

# Authenticated endpoints accessible to any logged-in user (no role check)
AUTH_NO_ROLE_CHECK_PATHS = {"/api/auth"}

# Endpoints accessible to any authenticated user regardless of role (read-only)
# GET /api/cdm/ is needed by the sidebar CDM selector for all users
AUTH_READ_PATHS = {"/api/cdm/"}

# Path patterns where CDM name appears as a path segment
_CDM_PATH_PATTERNS = [
    re.compile(r"^/api/quality/(?:snapshots|conformity|timeline|report)/([^/]+)"),
    re.compile(r"^/api/mapping/(?:dashboard|unmapped|strategies|concept-lookup|history|apply/export)/([^/]+)"),
    re.compile(r"^/api/cdm/([^/]+)"),
]

# Paths to skip CDM access check (admin-only endpoints, access-control itself)
_CDM_CHECK_SKIP_PREFIXES = {"/api/cdm-access"}

# ── SSE ticket store (one-time-use tokens for EventSource connections) ──
_SSE_TICKET_TTL = 30  # seconds
_MAX_SSE_TICKETS = 1000
_sse_tickets: dict[str, tuple[dict, float]] = {}  # ticket_id → (user_info, expires_at)
_sse_tickets_lock = threading.Lock()


def create_sse_ticket(user_info: dict) -> str:
    """Create a one-time-use ticket for SSE connections. Valid for 30 seconds."""
    with _sse_tickets_lock:
        # Cleanup expired tickets
        now = time.time()
        expired = [k for k, (_, exp) in _sse_tickets.items() if exp < now]
        for k in expired:
            del _sse_tickets[k]

        # Enforce maximum capacity
        if len(_sse_tickets) >= _MAX_SSE_TICKETS:
            # Expired tickets already cleaned above; reject if still at capacity
            raise HTTPException(status_code=429, detail="Too many active tickets")

        ticket_id = uuid.uuid4().hex
        _sse_tickets[ticket_id] = (user_info, now + _SSE_TICKET_TTL)
        return ticket_id


def _redeem_sse_ticket(ticket_id: str) -> dict | None:
    """Redeem and consume a one-time-use SSE ticket. Returns user_info or None."""
    with _sse_tickets_lock:
        entry = _sse_tickets.pop(ticket_id, None)
    if entry is None:
        return None
    user_info, expires_at = entry
    if time.time() > expires_at:
        return None
    return user_info


def _extract_cdm_name(request: Request) -> str | None:
    """Extract cdm_name from query params or known path patterns."""
    path = request.url.path

    for prefix in _CDM_CHECK_SKIP_PREFIXES:
        if path.startswith(prefix):
            return None

    cdm = request.query_params.get("cdm_name")
    if cdm:
        return cdm
    cdm_a = request.query_params.get("cdm_name_a")
    if cdm_a:
        return cdm_a

    for pattern in _CDM_PATH_PATTERNS:
        m = pattern.match(path)
        if m:
            return m.group(1)

    return None


def _check_cdm_access(cdm_name: str, user_info: dict) -> bool:
    """Check if user can access the given CDM.

    Uses permissions.yaml for role-based visibility:
    - Roles with cdm_visibility=all see everything
    - Roles with cdm_visibility=acl_only need explicit grant (user or group)
    - If NO ACL exists for a CDM, only full-visibility roles can see it
    """
    roles = user_info.get("roles", [])
    if has_any_full_visibility(roles):
        return True

    username = user_info.get("preferred_username", "anonymous")

    from db.app_db import SessionLocal
    from db.models import CdmAccess, CdmGroupAccess, UserGroupMember

    db = SessionLocal()
    try:
        # For acl_only roles: must have explicit grant (user or group)
        # Direct user grant
        user_access = db.query(CdmAccess).filter(
            CdmAccess.cdm_name == cdm_name,
            CdmAccess.username == username,
        ).first()
        if user_access:
            return True

        # Group grant: check if user belongs to any group that has access
        group_grants = db.query(CdmGroupAccess.group_name).filter(
            CdmGroupAccess.cdm_name == cdm_name,
        ).all()
        if group_grants:
            group_names = [g.group_name for g in group_grants]
            member = db.query(UserGroupMember).filter(
                UserGroupMember.group_name.in_(group_names),
                UserGroupMember.username == username,
            ).first()
            if member:
                return True

        return False
    finally:
        db.close()


def _extract_roles(token_payload: dict) -> list[str]:
    """Extract realm roles from token payload."""
    roles = token_payload.get("roles", [])
    if isinstance(roles, list) and roles:
        return roles
    realm_access = token_payload.get("realm_access", {})
    return realm_access.get("roles", [])


class KeycloakMiddleware:
    """Pure ASGI middleware for OIDC authentication with role-based route access.

    Unlike BaseHTTPMiddleware, this does NOT buffer response bodies, so
    StreamingResponse (SSE) works correctly with real-time event delivery.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = StarletteRequest(scope, receive, send)
        path = request.url.path

        # Let public endpoints through
        if path == "/" or any(path.startswith(p) for p in PUBLIC_PATHS if p != "/"):
            scope.setdefault("state", {})["user"] = {
                "sub": "anonymous", "preferred_username": "anonymous", "roles": [],
            }
            await self.app(scope, receive, send)
            return

        if not AUTH_ENABLED:
            logger.warning(
                "SECURITY: AUTH_ENABLED=false — all requests granted dev access (ENVIRONMENT=%s)",
                ENVIRONMENT,
            )
            scope.setdefault("state", {})["user"] = {
                "sub": "dev-user", "preferred_username": "dev-user", "roles": ["admin"],
            }
            await self.app(scope, receive, send)
            return

        # Check Authorization header, fallback to ?ticket= one-time ticket (for SSE/EventSource)
        auth_header = request.headers.get("Authorization", "")
        ticket_param = request.query_params.get("ticket", "")

        user_info = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                user_info = await _validate_token(token)
                roles = _extract_roles(user_info)
                user_info["roles"] = roles
            except Exception as e:
                logger.warning("Token validation failed: %s", e)
                resp = JSONResponse(status_code=401, content={"detail": "Invalid or expired token"})
                await resp(scope, receive, send)
                return
        elif ticket_param:
            user_info = _redeem_sse_ticket(ticket_param)
            if user_info is None:
                resp = JSONResponse(status_code=401, content={"detail": "Invalid or expired ticket"})
                await resp(scope, receive, send)
                return
        else:
            resp = JSONResponse(status_code=401, content={"detail": "Missing or invalid Authorization header"})
            await resp(scope, receive, send)
            return

        roles = user_info.get("roles", [])
        scope.setdefault("state", {})["user"] = user_info

        # Skip role check for auth-only endpoints (any authenticated user)
        if any(path.startswith(p) for p in AUTH_NO_ROLE_CHECK_PATHS):
            await self.app(scope, receive, send)
            return

        # Allow read-only access to certain endpoints for all authenticated users
        if request.method == "GET" and any(path.startswith(p) for p in AUTH_READ_PATHS):
            await self.app(scope, receive, send)
            return

        # Check role-based route access (driven by permissions.yaml)
        if not check_route_access(roles, path):
            resp = JSONResponse(
                status_code=403,
                content={"detail": "Forbidden: insufficient permissions for this resource"},
            )
            await resp(scope, receive, send)
            return

        # Check per-CDM access control
        cdm_name = _extract_cdm_name(request)
        if cdm_name and not _check_cdm_access(cdm_name, user_info):
            resp = JSONResponse(
                status_code=403,
                content={"detail": f"Access denied to CDM '{cdm_name}'"},
            )
            await resp(scope, receive, send)
            return

        await self.app(scope, receive, send)


async def _validate_token(token: str) -> dict:
    """Validate a JWT token locally using Keycloak JWKS keys."""
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        expected_issuer = f"{KEYCLOAK_ISSUER_URL}/realms/{KEYCLOAK_REALM}"
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=KEYCLOAK_CLIENT_ID,
            issuer=expected_issuer,
            leeway=30,  # M4: 30s clock skew tolerance
            options={
                "verify_iss": True,
                "verify_exp": True,
                "verify_aud": True,
            },
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Invalid token: {e}")


def get_current_user(request: Request) -> dict:
    """FastAPI dependency to get the current user from request state."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_roles(*allowed_roles: str):
    """FastAPI dependency factory: require at least one of the given roles."""
    def checker(request: Request):
        user = get_current_user(request)
        user_roles = user.get("roles", [])
        if not any(r in user_roles for r in allowed_roles):
            raise HTTPException(status_code=403, detail="Forbidden: insufficient permissions")
        return user
    return Depends(checker)
