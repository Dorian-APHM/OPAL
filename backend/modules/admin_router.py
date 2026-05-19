"""
Admin endpoints — Keycloak user management, access requests.

Extracted from main.py to keep the entry point lean.
"""
import logging
import os
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import KEYCLOAK_URL, KEYCLOAK_REALM
from db.app_db import get_db
from utils.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin"])

def _generate_temp_password(length: int = 20) -> str:
    """Generate a temporary password that satisfies common Keycloak password policies.

    Guarantees at least 1 uppercase, 1 digit, and 1 special character.
    """
    specials = "!@#$%&*"
    # Guarantee required character classes
    mandatory = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice(specials),
    ]
    alphabet = string.ascii_letters + string.digits + specials
    remaining = [secrets.choice(alphabet) for _ in range(length - len(mandatory))]
    chars = mandatory + remaining
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


# Cache LDAP detection result for 60s to avoid hitting Keycloak on every request
_ldap_cache: dict = {"value": None, "ts": 0.0}
_LDAP_CACHE_TTL = 60.0


class AssignRoleRequest(BaseModel):
    role: str = Field(..., min_length=1, max_length=100)


class ToggleUserRequest(BaseModel):
    enabled: bool


def _require_admin(request: Request):
    """Raise 403 if the current user doesn't have the admin role."""
    user = getattr(request.state, "user", {})
    roles = user.get("roles", [])
    if "admin" not in roles:
        raise HTTPException(status_code=403, detail="Forbidden: admin role required")
    return user


def _get_keycloak_admin_token() -> str | None:
    """Get a Keycloak admin token using client credentials or admin password."""
    import requests as http_requests

    admin_user = os.getenv("KEYCLOAK_ADMIN", "")
    admin_pass = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "")

    if not admin_user or not admin_pass:
        logger.error("KEYCLOAK_ADMIN / KEYCLOAK_ADMIN_PASSWORD not configured")
        return None

    if admin_user == "admin" and admin_pass == "admin":
        logger.warning(
            "SECURITY: Keycloak admin credentials are set to default 'admin/admin'. "
            "Change KEYCLOAK_ADMIN and KEYCLOAK_ADMIN_PASSWORD in your .env file for production."
        )

    try:
        resp = http_requests.post(
            f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": admin_user,
                "password": admin_pass,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("access_token")
    except Exception as e:
        logger.warning("Failed to get Keycloak admin token: %s", e)
        return None


def _has_ldap_federation(token: str) -> bool:
    """Detect if a UserStorageProvider (LDAP) is configured in the Keycloak realm.

    Queries the Keycloak components API and caches the result for 60s.
    Falls back to the KEYCLOAK_LDAP_ENABLED env var if the API call fails.
    """
    import time
    import requests as http_requests

    now = time.monotonic()
    if _ldap_cache["value"] is not None and (now - _ldap_cache["ts"]) < _LDAP_CACHE_TTL:
        return _ldap_cache["value"]

    try:
        base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
        resp = http_requests.get(
            f"{base}/components?type=org.keycloak.storage.UserStorageProvider",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        resp.raise_for_status()
        components = resp.json()
        has_ldap = any(
            c.get("providerId") == "ldap" and c.get("config", {}).get("enabled", ["true"])[0] == "true"
            for c in components
        )
        _ldap_cache["value"] = has_ldap
        _ldap_cache["ts"] = now
        return has_ldap
    except Exception as e:
        logger.warning("Failed to detect LDAP federation, falling back to env var: %s", e)
        return os.environ.get("KEYCLOAK_LDAP_ENABLED", "false").lower() == "true"


# ──── Admin: User Management (Keycloak proxy) ────

@router.get("/api/admin/users")
def list_users(request: Request, admin_user=Depends(_require_admin)):
    """List Keycloak users with their roles (admin only)."""
    import requests as http_requests
    token = _get_keycloak_admin_token()
    if not token:
        return {"users": [], "error": "Keycloak admin unavailable"}

    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {token}"}

    opal_roles = ["admin", "data-manager", "chercheur", "medecin"]
    user_map = {}

    try:
        for role_name in opal_roles:
            resp = http_requests.get(
                f"{base}/roles/{role_name}/users?max=200", headers=headers, timeout=10
            )
            if not resp.ok:
                continue
            for u in resp.json():
                uid = u["id"]
                if uid not in user_map:
                    user_map[uid] = {
                        "id": uid,
                        "username": u.get("username", ""),
                        "email": u.get("email", ""),
                        "first_name": u.get("firstName", ""),
                        "last_name": u.get("lastName", ""),
                        "enabled": u.get("enabled", False),
                        "created_at": u.get("createdTimestamp"),
                        "roles": [],
                    }
                user_map[uid]["roles"].append(role_name)
    except Exception as e:
        logger.warning("Failed to fetch Keycloak users: %s", e)
        return {"users": [], "error": str(e)}

    return {"users": list(user_map.values())}


@router.post("/api/admin/users/{user_id}/roles")
def assign_role(user_id: str, request: Request, body: AssignRoleRequest, admin_user=Depends(_require_admin)):
    """Assign a role to a Keycloak user (admin only)."""
    import requests as http_requests
    role_name = body.role

    token = _get_keycloak_admin_token()
    if not token:
        return JSONResponse(status_code=503, content={"detail": "Keycloak admin unavailable"})

    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        role_resp = http_requests.get(f"{base}/roles/{role_name}", headers=headers, timeout=5)
        role_resp.raise_for_status()
        role_obj = role_resp.json()
    except Exception:
        return JSONResponse(status_code=404, content={"detail": f"Role '{role_name}' not found"})

    try:
        resp = http_requests.post(
            f"{base}/users/{user_id}/role-mappings/realm",
            headers=headers, json=[role_obj], timeout=5,
        )
        resp.raise_for_status()
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Failed to assign role: {e}"})

    return {"status": "ok", "user_id": user_id, "role": role_name, "action": "assigned"}


@router.delete("/api/admin/users/{user_id}/roles/{role_name}")
def remove_role(user_id: str, role_name: str, request: Request, admin_user=Depends(_require_admin)):
    """Remove a role from a Keycloak user (admin only)."""
    import requests as http_requests
    token = _get_keycloak_admin_token()
    if not token:
        return JSONResponse(status_code=503, content={"detail": "Keycloak admin unavailable"})

    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        role_resp = http_requests.get(f"{base}/roles/{role_name}", headers=headers, timeout=5)
        role_resp.raise_for_status()
        role_obj = role_resp.json()
    except Exception:
        return JSONResponse(status_code=404, content={"detail": f"Role '{role_name}' not found"})

    try:
        resp = http_requests.delete(
            f"{base}/users/{user_id}/role-mappings/realm",
            headers=headers, json=[role_obj], timeout=5,
        )
        resp.raise_for_status()
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Failed to remove role: {e}"})

    return {"status": "ok", "user_id": user_id, "role": role_name, "action": "removed"}


@router.put("/api/admin/users/{user_id}/toggle")
def toggle_user(user_id: str, request: Request, body: ToggleUserRequest, admin_user=Depends(_require_admin)):
    """Enable or disable a Keycloak user (admin only)."""
    import requests as http_requests
    enabled = body.enabled
    token = _get_keycloak_admin_token()
    if not token:
        return JSONResponse(status_code=503, content={"detail": "Keycloak admin unavailable"})

    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        resp = http_requests.put(
            f"{base}/users/{user_id}", headers=headers, json={"enabled": enabled}, timeout=5,
        )
        resp.raise_for_status()
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Failed to update user: {e}"})

    return {"status": "ok", "user_id": user_id, "enabled": enabled}


# ──── Access Requests (self-service sign-up) ────

@router.post("/api/access-requests")
@limiter.limit("5/minute")
def submit_access_request(request: Request, body: dict, db=Depends(get_db)):
    """Submit a new access request (public, no auth required)."""
    from db.models import AccessRequest

    required = ["username", "requested_role"]
    for field in required:
        if not body.get(field, "").strip():
            return JSONResponse(status_code=400, content={"detail": f"{field} is required"})

    role = body["requested_role"]
    if role not in ("admin", "data-manager", "chercheur", "medecin"):
        return JSONResponse(status_code=400, content={"detail": f"Invalid role: {role}"})

    existing = db.query(AccessRequest).filter(
        AccessRequest.username == body["username"],
        AccessRequest.status == "pending",
    ).first()
    if existing:
        return JSONResponse(status_code=409, content={"detail": "Une demande est deja en cours pour ce matricule"})

    req = AccessRequest(
        username=body["username"].strip(),
        email=body.get("email", "").strip(),
        first_name=body.get("first_name", "").strip(),
        last_name=body.get("last_name", "").strip(),
        requested_role=role,
    )
    db.add(req)
    db.flush()

    from utils.notifications import notify
    notify(
        db, body["username"], "access_request",
        title=f"Nouvelle demande d'accès : {body['username']}",
        message=f"{body['username']} demande le rôle « {role} ».",
        link="/users",
        target_role="admin",
        item_id=str(req.id),
    )

    db.commit()
    return {"status": "ok", "id": req.id}


@router.get("/api/admin/access-requests")
def list_access_requests(request: Request, status_filter: str = "pending", admin_user=Depends(_require_admin), db=Depends(get_db)):
    """List access requests (admin only)."""
    from db.models import AccessRequest

    q = db.query(AccessRequest)
    if status_filter != "all":
        q = q.filter(AccessRequest.status == status_filter)
    requests_list = q.order_by(AccessRequest.created_at.desc()).all()
    return {
        "requests": [
            {
                "id": r.id,
                "username": r.username,
                "email": r.email,
                "first_name": r.first_name,
                "last_name": r.last_name,
                "requested_role": r.requested_role,
                "status": r.status,
                "reviewed_by": r.reviewed_by,
                "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in requests_list
        ]
    }


@router.post("/api/admin/access-requests/{request_id}/approve")
def approve_access_request(request_id: int, request: Request, admin_user=Depends(_require_admin), db=Depends(get_db)):
    """Approve an access request: create Keycloak user with temporary password (admin only)."""
    import requests as http_requests
    from datetime import datetime, timezone
    from db.models import AccessRequest

    ar = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not ar:
        return JSONResponse(status_code=404, content={"detail": "Request not found"})
    if ar.status != "pending":
        return JSONResponse(status_code=400, content={"detail": f"Request already {ar.status}"})

    token = _get_keycloak_admin_token()
    if not token:
        return JSONResponse(status_code=503, content={"detail": "Keycloak admin unavailable"})

    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    use_ldap = _has_ldap_federation(token)
    kc_user_id = None

    try:
        search_resp = http_requests.get(
            f"{base}/users?username={ar.username}&exact=true", headers=headers, timeout=10
        )
        existing = [u for u in search_resp.json() if u.get("username", "").lower() == ar.username.lower()] if search_resp.ok else []
        if existing:
            kc_user_id = existing[0]["id"]
    except Exception:
        pass

    temp_password = _generate_temp_password()
    if not kc_user_id:
        user_payload = {
            "username": ar.username,
            "email": ar.email,
            "firstName": ar.first_name,
            "lastName": ar.last_name,
            "enabled": True,
        }
        if not use_ldap:
            user_payload["credentials"] = [{
                "type": "password",
                "value": temp_password,
                "temporary": True,
            }]
        try:
            resp = http_requests.post(f"{base}/users", headers=headers, json=user_payload, timeout=10)
            resp.raise_for_status()
            location = resp.headers.get("Location", "")
            kc_user_id = location.rsplit("/", 1)[-1] if location else None
        except Exception as e:
            return JSONResponse(status_code=500, content={"detail": f"Failed to create Keycloak user: {e}"})
    elif not use_ldap:
        # User already exists — force reset password so the displayed temp password is valid
        try:
            http_requests.put(
                f"{base}/users/{kc_user_id}/reset-password",
                headers=headers,
                json={"type": "password", "value": temp_password, "temporary": True},
                timeout=5,
            ).raise_for_status()
        except Exception as e:
            return JSONResponse(status_code=500, content={"detail": f"Failed to reset password: {e}"})

    if kc_user_id and ar.requested_role:
        try:
            role_resp = http_requests.get(
                f"{base}/roles/{ar.requested_role}", headers=headers, timeout=5
            )
            if role_resp.ok:
                role_obj = role_resp.json()
                http_requests.post(
                    f"{base}/users/{kc_user_id}/role-mappings/realm",
                    headers=headers, json=[role_obj], timeout=5,
                )
        except Exception:
            logger.warning("Failed to assign role %s to new user %s", ar.requested_role, ar.username)

    user_info = getattr(request.state, "user", {})
    ar.status = "approved"
    ar.reviewed_by = user_info.get("preferred_username", "admin")
    ar.reviewed_at = datetime.now(timezone.utc)

    from utils.notifications import notify
    notify(
        db, ar.username, "access_request",
        title="Demande d'accès approuvée",
        message=f"Votre demande d'accès avec le rôle « {ar.requested_role} » a été approuvée.",
        item_id=str(ar.id),
    )

    db.commit()

    result = {
        "status": "ok",
        "username": ar.username,
        "keycloak_user_id": kc_user_id,
    }
    if not use_ldap:
        result["temporary_password"] = temp_password
    else:
        result["auth_method"] = "ldap"
    return result


@router.post("/api/admin/users/add")
async def add_user_direct(request: Request, admin_user=Depends(_require_admin)):
    """Admin adds a user directly by matricule + role (admin only)."""
    import requests as http_requests

    body = await request.json()
    username = body.get("username", "").strip()
    role = body.get("role", "").strip()

    if not username:
        return JSONResponse(status_code=400, content={"detail": "Matricule requis"})
    if role not in ("admin", "data-manager", "chercheur", "medecin"):
        return JSONResponse(status_code=400, content={"detail": f"Role invalide: {role}"})

    token = _get_keycloak_admin_token()
    if not token:
        return JSONResponse(status_code=503, content={"detail": "Keycloak admin unavailable"})

    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    use_ldap = _has_ldap_federation(token)
    kc_user_id = None

    try:
        search_resp = http_requests.get(
            f"{base}/users?username={username}&exact=true", headers=headers, timeout=10
        )
        existing = [u for u in search_resp.json() if u.get("username", "").lower() == username.lower()] if search_resp.ok else []
        if existing:
            kc_user_id = existing[0]["id"]
    except Exception:
        pass

    temp_password = _generate_temp_password()
    if not kc_user_id:
        user_payload = {"username": username, "enabled": True}
        if not use_ldap:
            user_payload["credentials"] = [{"type": "password", "value": temp_password, "temporary": True}]
        try:
            resp = http_requests.post(f"{base}/users", headers=headers, json=user_payload, timeout=10)
            resp.raise_for_status()
            location = resp.headers.get("Location", "")
            kc_user_id = location.rsplit("/", 1)[-1] if location else None
        except Exception as e:
            return JSONResponse(status_code=500, content={"detail": f"Impossible de creer l'utilisateur: {e}"})
    elif not use_ldap:
        # User already exists — force reset password so the displayed temp password is valid
        try:
            http_requests.put(
                f"{base}/users/{kc_user_id}/reset-password",
                headers=headers,
                json={"type": "password", "value": temp_password, "temporary": True},
                timeout=5,
            ).raise_for_status()
        except Exception as e:
            return JSONResponse(status_code=500, content={"detail": f"Impossible de reinitialiser le mot de passe: {e}"})

    if not kc_user_id:
        return JSONResponse(status_code=500, content={"detail": "Impossible de trouver ou creer l'utilisateur"})

    try:
        role_resp = http_requests.get(f"{base}/roles/{role}", headers=headers, timeout=5)
        if role_resp.ok:
            role_obj = role_resp.json()
            assign_resp = http_requests.post(
                f"{base}/users/{kc_user_id}/role-mappings/realm",
                headers=headers, json=[role_obj], timeout=5,
            )
            assign_resp.raise_for_status()
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Utilisateur cree mais echec assignation role: {e}"})

    result = {"status": "ok", "username": username, "role": role, "keycloak_user_id": kc_user_id}
    if not use_ldap:
        result["temporary_password"] = temp_password
    return result


@router.post("/api/admin/access-requests/{request_id}/reject")
def reject_access_request(request_id: int, request: Request, admin_user=Depends(_require_admin), db=Depends(get_db)):
    """Reject an access request (admin only)."""
    from datetime import datetime, timezone
    from db.models import AccessRequest

    ar = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not ar:
        return JSONResponse(status_code=404, content={"detail": "Request not found"})
    if ar.status != "pending":
        return JSONResponse(status_code=400, content={"detail": f"Request already {ar.status}"})

    user_info = getattr(request.state, "user", {})
    ar.status = "rejected"
    ar.reviewed_by = user_info.get("preferred_username", "admin")
    ar.reviewed_at = datetime.now(timezone.utc)

    from utils.notifications import notify
    notify(
        db, ar.username, "access_request",
        title="Demande d'accès refusée",
        message=f"Votre demande d'accès avec le rôle « {ar.requested_role} » a été refusée.",
        item_id=str(ar.id),
    )

    db.commit()

    return {"status": "ok", "id": ar.id}


@router.get("/api/users/list")
def list_opal_users(request: Request):
    """List usernames of all users who have an OPAL role.

    Available to any authenticated user (for sharing dropdowns).
    Returns only usernames — no admin details.
    """
    import requests as http_requests
    token = _get_keycloak_admin_token()
    if not token:
        return {"users": []}

    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {token}"}
    opal_roles = ["admin", "data-manager", "chercheur", "medecin"]
    usernames = set()

    try:
        for role_name in opal_roles:
            resp = http_requests.get(
                f"{base}/roles/{role_name}/users?max=500", headers=headers, timeout=10
            )
            if not resp.ok:
                continue
            for u in resp.json():
                uname = u.get("username", "")
                if uname:
                    usernames.add(uname)
    except Exception as e:
        logger.warning("Failed to fetch OPAL users: %s", e)
        return {"users": []}

    return {"users": sorted(usernames)}
