from __future__ import annotations

"""
CDM Access Control endpoints.

Manages per-user and per-group access to CDM databases.
Admin assigns access; middleware filters CDM list.
Visibility rules driven by permissions.yaml.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.app_db import get_db
from db.models import CdmAccess, CdmGroupAccess, CdmConfig, UserGroupMember
from auth.permissions import has_any_full_visibility, can_manage_access as _can_manage, can_clear_all_grants as _can_clear
from utils.notifications import notify

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cdm-access", tags=["cdm-access"])


def _require_manage_access(request: Request):
    """Raise 403 if the current user's roles don't have can_manage_access."""
    user = getattr(request.state, "user", {})
    roles = user.get("roles", [])
    if not any(_can_manage(r) for r in roles):
        raise HTTPException(status_code=403, detail="Forbidden: insufficient permissions to manage CDM access")
    return user


def _require_clear_all(request: Request):
    """Raise 403 if the current user's roles don't have can_clear_all_grants."""
    user = getattr(request.state, "user", {})
    roles = user.get("roles", [])
    if not any(_can_clear(r) for r in roles):
        raise HTTPException(status_code=403, detail="Forbidden: insufficient permissions to clear all CDM grants")
    return user


def _user_has_cdm_access(cdm_name: str, username: str, db: Session) -> bool:
    """Check if a user has access to a CDM via direct grant or group membership."""
    from sqlalchemy import exists, and_

    # Direct user grant
    direct = exists().where(
        and_(CdmAccess.cdm_name == cdm_name, CdmAccess.username == username)
    )

    # Group grant: single EXISTS with JOIN instead of N+1 queries
    via_group = exists().where(
        and_(
            CdmGroupAccess.cdm_name == cdm_name,
            UserGroupMember.group_name == CdmGroupAccess.group_name,
            UserGroupMember.username == username,
        )
    )

    return db.query(direct | via_group).scalar()


def _cdm_has_acl(cdm_name: str, db: Session) -> bool:
    """Check if a CDM has any access control (user or group)."""
    from sqlalchemy import exists, and_

    has_acl = exists().where(and_(CdmAccess.cdm_name == cdm_name)) | \
              exists().where(and_(CdmGroupAccess.cdm_name == cdm_name))
    return db.query(has_acl).scalar()


def check_cdm_access(cdm_name: str, request: Request, db: Session) -> None:
    """Raise 403 if the current user cannot access the given CDM.

    Rules (driven by permissions.yaml cdm_visibility):
    - Roles with cdm_visibility=all -> always allowed (admin, data-manager)
    - Roles with cdm_visibility=acl_only -> must have explicit grant (user or group)
    - If NO ACL exists for a CDM, only full-visibility roles can see it
    """
    user = getattr(request.state, "user", {})
    roles = user.get("roles", [])
    if has_any_full_visibility(roles):
        return
    username = user.get("preferred_username", "anonymous")
    if not _user_has_cdm_access(cdm_name, username, db):
        raise HTTPException(status_code=403, detail=f"Access denied to CDM '{cdm_name}'")


class GrantAccessRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)


class GrantGroupAccessRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1)
    group_name: str = Field(..., min_length=1)


class RevokeAccessRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)


class RevokeGroupAccessRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1)
    group_name: str = Field(..., min_length=1)


@router.get("/")
def list_access(
    request: Request,
    cdm_name: str | None = None,
    username: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user=Depends(_require_manage_access),
    db: Session = Depends(get_db),
):
    """List CDM access grants (user + group), optionally filtered."""
    # User grants
    q = db.query(CdmAccess)
    if cdm_name:
        q = q.filter(CdmAccess.cdm_name == cdm_name)
    if username:
        q = q.filter(CdmAccess.username == username)
    total_user = q.count()
    user_rows = q.order_by(CdmAccess.created_at.desc()).offset(offset).limit(limit).all()

    # Group grants
    gq = db.query(CdmGroupAccess)
    if cdm_name:
        gq = gq.filter(CdmGroupAccess.cdm_name == cdm_name)
    total_group = gq.count()
    group_rows = gq.order_by(CdmGroupAccess.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "grants": [
            {
                "id": r.id,
                "cdm_name": r.cdm_name,
                "username": r.username,
                "grant_type": "user",
                "granted_by": r.granted_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in user_rows
        ],
        "group_grants": [
            {
                "id": r.id,
                "cdm_name": r.cdm_name,
                "group_name": r.group_name,
                "grant_type": "group",
                "granted_by": r.granted_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in group_rows
        ],
        "total_user_grants": total_user,
        "total_group_grants": total_group,
        "limit": limit,
        "offset": offset,
    }


@router.get("/cdms-for-user")
def get_accessible_cdms(
    request: Request,
    db: Session = Depends(get_db),
):
    """Return list of CDM names the current user can access.

    Visibility driven by permissions.yaml:
    - cdm_visibility=all -> sees all CDMs (admin, data-manager)
    - cdm_visibility=acl_only -> only CDMs with explicit grant (user or group)
    """
    user = getattr(request.state, "user", {})
    username = user.get("preferred_username", "anonymous")
    roles = user.get("roles", [])

    # Full-visibility roles see everything
    if has_any_full_visibility(roles):
        all_cdms = db.query(CdmConfig.name).all()
        return {"cdms": [c.name for c in all_cdms]}

    # acl_only roles: single query with JOIN instead of N+1
    # Direct user grants
    direct_cdms = db.query(CdmAccess.cdm_name).filter(
        CdmAccess.username == username,
    ).all()

    # Group-based grants: find groups user belongs to, then CDMs those groups can access
    user_groups_select = db.query(UserGroupMember.group_name).filter(
        UserGroupMember.username == username,
    ).scalar_subquery()
    group_cdms = db.query(CdmGroupAccess.cdm_name).filter(
        CdmGroupAccess.group_name.in_(user_groups_select),
    ).all()

    result = sorted(set(c.cdm_name for c in direct_cdms) | set(c.cdm_name for c in group_cdms))
    return {"cdms": result}


@router.post("/grant")
def grant_access(req: GrantAccessRequest, request: Request, user=Depends(_require_manage_access), db: Session = Depends(get_db)):
    """Grant a user access to a CDM (requires can_manage_access)."""
    cdm = db.query(CdmConfig).filter(CdmConfig.name == req.cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{req.cdm_name}' not found")

    existing = db.query(CdmAccess).filter(
        CdmAccess.cdm_name == req.cdm_name,
        CdmAccess.username == req.username,
    ).first()
    if existing:
        return {"status": "already_granted", "id": existing.id}

    user = getattr(request.state, "user", {})
    granted_by = user.get("preferred_username", "admin")
    access = CdmAccess(
        cdm_name=req.cdm_name,
        username=req.username,
        granted_by=granted_by,
    )
    db.add(access)

    try:
        notify(
            db, req.username, "access_granted",
            title=f"Accès accordé : {req.cdm_name}",
            message=f"{granted_by} vous a accordé l'accès à la base CDM « {req.cdm_name} ».",
            link="/quality",
            item_id=req.cdm_name,
        )

        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to grant access to CDM '%s' for user '%s'", req.cdm_name, req.username)
        raise HTTPException(status_code=500, detail="Failed to grant access")
    return {"status": "ok", "id": access.id}


@router.post("/grant-group")
def grant_group_access(req: GrantGroupAccessRequest, request: Request, user=Depends(_require_manage_access), db: Session = Depends(get_db)):
    """Grant a user group access to a CDM (requires can_manage_access).
    All members of the group will have access. Membership is resolved dynamically.
    """
    cdm = db.query(CdmConfig).filter(CdmConfig.name == req.cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{req.cdm_name}' not found")

    from db.models import UserGroup
    group = db.query(UserGroup).filter(UserGroup.name == req.group_name).first()
    if not group:
        raise HTTPException(status_code=404, detail=f"Group '{req.group_name}' not found")

    existing = db.query(CdmGroupAccess).filter(
        CdmGroupAccess.cdm_name == req.cdm_name,
        CdmGroupAccess.group_name == req.group_name,
    ).first()
    if existing:
        return {"status": "already_granted", "id": existing.id}

    user = getattr(request.state, "user", {})
    granted_by = user.get("preferred_username", "admin")
    access = CdmGroupAccess(
        cdm_name=req.cdm_name,
        group_name=req.group_name,
        granted_by=granted_by,
    )
    db.add(access)

    # Notify all group members
    members = db.query(UserGroupMember).filter(UserGroupMember.group_name == req.group_name).all()
    for m in members:
        notify(
            db, m.username, "access_granted",
            title=f"Accès accordé : {req.cdm_name}",
            message=f"Le groupe « {req.group_name} » a reçu l'accès à la base CDM « {req.cdm_name} ».",
            link="/quality",
            item_id=req.cdm_name,
        )

    db.commit()
    return {"status": "ok", "id": access.id}


@router.post("/revoke")
def revoke_access(req: RevokeAccessRequest, request: Request, user=Depends(_require_manage_access), db: Session = Depends(get_db)):
    """Revoke a user's access to a CDM (requires can_manage_access)."""
    access = db.query(CdmAccess).filter(
        CdmAccess.cdm_name == req.cdm_name,
        CdmAccess.username == req.username,
    ).first()
    if not access:
        raise HTTPException(status_code=404, detail="Access grant not found")

    admin_user = getattr(request.state, "user", {})
    admin_name = admin_user.get("preferred_username", "admin")

    notify(
        db, req.username, "access_revoked",
        title=f"Accès révoqué : {req.cdm_name}",
        message=f"{admin_name} a révoqué votre accès à la base CDM « {req.cdm_name} ».",
        link="/",
        item_id=req.cdm_name,
    )

    db.delete(access)
    db.commit()
    return {"status": "ok"}


@router.post("/revoke-group")
def revoke_group_access(req: RevokeGroupAccessRequest, request: Request, user=Depends(_require_manage_access), db: Session = Depends(get_db)):
    """Revoke a group's access to a CDM (requires can_manage_access)."""
    access = db.query(CdmGroupAccess).filter(
        CdmGroupAccess.cdm_name == req.cdm_name,
        CdmGroupAccess.group_name == req.group_name,
    ).first()
    if not access:
        raise HTTPException(status_code=404, detail="Group access grant not found")

    admin_user = getattr(request.state, "user", {})
    admin_name = admin_user.get("preferred_username", "admin")

    # Notify all group members before revoking
    members = db.query(UserGroupMember).filter(UserGroupMember.group_name == req.group_name).all()
    for m in members:
        notify(
            db, m.username, "access_revoked",
            title=f"Accès révoqué : {req.cdm_name}",
            message=f"{admin_name} a révoqué l'accès du groupe « {req.group_name} » à la base CDM « {req.cdm_name} ».",
            link="/",
            item_id=req.cdm_name,
        )

    db.delete(access)
    db.commit()
    return {"status": "ok"}


@router.delete("/cdm/{cdm_name}")
def clear_cdm_access(cdm_name: str, request: Request, user=Depends(_require_clear_all), db: Session = Depends(get_db)):
    """Remove all access controls for a CDM (requires can_clear_all_grants)."""
    try:
        deleted_users = db.query(CdmAccess).filter(CdmAccess.cdm_name == cdm_name).delete()
        deleted_groups = db.query(CdmGroupAccess).filter(CdmGroupAccess.cdm_name == cdm_name).delete()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to clear access for CDM '%s'", cdm_name)
        raise HTTPException(status_code=500, detail="Failed to clear CDM access")
    return {"status": "ok", "deleted_users": deleted_users, "deleted_groups": deleted_groups}
