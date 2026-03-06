"""
Keycloak OIDC authentication middleware with role-based access control.
Validates JWT tokens locally using JWKS keys (no issuer hostname dependency).
"""
import logging

import jwt
from jwt import PyJWKClient
from fastapi import Request, HTTPException, Depends
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from config import AUTH_ENABLED, KEYCLOAK_URL, KEYCLOAK_REALM

logger = logging.getLogger(__name__)

# JWKS client for local JWT validation (caches keys automatically)
_jwks_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
_jwks_client = PyJWKClient(_jwks_url, cache_keys=True, lifespan=3600)

# Public endpoints that don't require authentication
PUBLIC_PATHS = {"/api/health", "/api/i18n", "/docs", "/openapi.json", "/redoc", "/"}

# Authenticated endpoints accessible to any logged-in user (no role check)
AUTH_NO_ROLE_CHECK_PATHS = {"/api/auth"}

# Role-to-route access map
# admin and omop-dim: access to everything (None = no restriction)
# chercheur: Quality, Cohorting, Concept Explorer
# medecin: Mapping, Cohorting, Concept Explorer
# CDM Management, Settings, OHDSI: admin and omop-dim only
ROLE_ROUTE_ACCESS = {
    "admin": None,
    "omop-dim": None,
    "chercheur": ["/api/quality", "/api/cohorts", "/api/concepts", "/api/i18n", "/api/health"],
    "medecin": ["/api/mapping", "/api/cohorts", "/api/concepts", "/api/i18n", "/api/health"],
}

# Endpoints accessible to any authenticated user regardless of role (read-only)
# GET /api/cdm/ is needed by the sidebar CDM selector for all users
AUTH_READ_PATHS = {"/api/cdm/"}


def _extract_roles(token_payload: dict) -> list[str]:
    """Extract realm roles from token payload.

    Roles can be in:
    - token_payload["roles"] (custom mapper we configured)
    - token_payload["realm_access"]["roles"] (default Keycloak structure)
    """
    roles = token_payload.get("roles", [])
    if isinstance(roles, list) and roles:
        return roles
    realm_access = token_payload.get("realm_access", {})
    return realm_access.get("roles", [])


def _check_route_access(roles: list[str], path: str) -> bool:
    """Check if any of the user's roles allow access to the given path."""
    for role in roles:
        allowed = ROLE_ROUTE_ACCESS.get(role)
        if allowed is None and role in ROLE_ROUTE_ACCESS:
            return True  # admin/omop-dim: access to everything
        if allowed:
            for prefix in allowed:
                if path.startswith(prefix):
                    return True
    return False


class KeycloakMiddleware(BaseHTTPMiddleware):
    """OIDC authentication middleware with role-based route access."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Let public endpoints through
        if path == "/" or any(path.startswith(p) for p in PUBLIC_PATHS if p != "/"):
            request.state.user = {"sub": "anonymous", "preferred_username": "anonymous", "roles": []}
            return await call_next(request)

        if not AUTH_ENABLED:
            request.state.user = {"sub": "default", "preferred_username": "user", "roles": ["admin"]}
            return await call_next(request)

        # Check Authorization header, fallback to ?token= query param (for SSE/EventSource)
        auth_header = request.headers.get("Authorization", "")
        token_param = request.query_params.get("token", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        elif token_param:
            token = token_param
        else:
            return JSONResponse(status_code=401, content={"detail": "Missing or invalid Authorization header"})
        try:
            user_info = await _validate_token(token)
            roles = _extract_roles(user_info)
            user_info["roles"] = roles
            request.state.user = user_info
        except Exception as e:
            logger.warning("Token validation failed: %s", e)
            return JSONResponse(status_code=401, content={"detail": "Invalid or expired token"})

        # Skip role check for auth-only endpoints (any authenticated user)
        if any(path.startswith(p) for p in AUTH_NO_ROLE_CHECK_PATHS):
            return await call_next(request)

        # Allow read-only access to certain endpoints for all authenticated users
        if request.method == "GET" and any(path.startswith(p) for p in AUTH_READ_PATHS):
            return await call_next(request)

        # Check role-based route access
        if not _check_route_access(roles, path):
            return JSONResponse(
                status_code=403,
                content={"detail": "Forbidden: insufficient permissions for this resource"},
            )

        return await call_next(request)


async def _validate_token(token: str) -> dict:
    """Validate a JWT token locally using Keycloak JWKS keys.

    This avoids the issuer hostname mismatch problem when the backend
    reaches Keycloak via Docker internal hostname (opal-keycloak:8080)
    but tokens are issued with the browser-facing hostname (localhost:8080).
    """
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={
                "verify_iss": False,
                "verify_exp": True,
                "verify_aud": False,
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
