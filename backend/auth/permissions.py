"""
Loads the permissions matrix from permissions.yaml.
Single source of truth for role-based access control.
"""
import os
import yaml

_YAML_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "permissions.yaml")

with open(_YAML_PATH, "r") as f:
    _config = yaml.safe_load(f)

ROLES: dict = _config["roles"]


def get_role_names() -> list[str]:
    """Return all defined role names."""
    return list(ROLES.keys())


def get_role_config(role: str) -> dict | None:
    """Return config for a single role, or None if unknown."""
    return ROLES.get(role)


def get_api_prefixes(role: str) -> list[str] | None:
    """Return list of allowed API prefixes for a role, or None if 'all'."""
    cfg = ROLES.get(role)
    if not cfg:
        return []
    api = cfg.get("api")
    if api == "all":
        return None  # unrestricted
    return api or []


def get_page_routes(role: str) -> list[str] | None:
    """Return list of allowed frontend page routes for a role, or None if 'all'."""
    cfg = ROLES.get(role)
    if not cfg:
        return []
    pages = cfg.get("pages")
    if pages == "all":
        return None  # unrestricted
    return pages or []


def has_cdm_full_visibility(role: str) -> bool:
    """Return True if this role can see all CDMs without ACL."""
    cfg = ROLES.get(role, {})
    return cfg.get("cdm_visibility") == "all"


def can_manage_access(role: str) -> bool:
    """Return True if this role can grant/revoke CDM access."""
    cfg = ROLES.get(role, {})
    return cfg.get("can_manage_access", False)


def can_clear_all_grants(role: str) -> bool:
    """Return True if this role can wipe all grants for a CDM."""
    cfg = ROLES.get(role, {})
    return cfg.get("can_clear_all_grants", False)


def check_route_access(roles: list[str], path: str) -> bool:
    """Check if any of the user's roles allow access to the given API path."""
    for role in roles:
        prefixes = get_api_prefixes(role)
        if prefixes is None:
            return True  # unrestricted role (admin, data-manager)
        for prefix in prefixes:
            if path.startswith(prefix):
                return True
    return False


def has_any_full_visibility(roles: list[str]) -> bool:
    """Check if any of the user's roles grants full CDM visibility."""
    return any(has_cdm_full_visibility(r) for r in roles)


def build_frontend_permissions(roles: list[str]) -> dict:
    """Build the permissions object to send to the frontend for a set of roles."""
    pages: set[str] | None = None  # None = all
    all_pages = False

    for role in roles:
        role_pages = get_page_routes(role)
        if role_pages is None:
            all_pages = True
            break
        if pages is None:
            pages = set()
        pages.update(role_pages)

    return {
        "roles": roles,
        "pages": "all" if all_pages else sorted(pages or []),
        "cdm_visibility": "all" if has_any_full_visibility(roles) else "acl_only",
        "can_manage_access": any(can_manage_access(r) for r in roles),
        "can_clear_all_grants": any(can_clear_all_grants(r) for r in roles),
    }
