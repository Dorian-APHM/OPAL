"""
Cohort sharing & user group management endpoints.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.app_db import get_db
from db.models import Cohort, CohortShare, CdmAccess, UserGroup, UserGroupMember
from utils.notifications import notify as _notify

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cohorts", tags=["cohort-sharing"])


# ── Pydantic models ──

class ShareRequest(BaseModel):
    share_type: str  # "user", "group", "all"
    share_target: str = ""  # username or group name (ignored when share_type="all")


class UnshareRequest(BaseModel):
    share_type: str
    share_target: str = ""


# ── Helpers ──

def _get_user(request: Request) -> dict:
    return getattr(request.state, "user", {})


def _require_owner_or_admin(db: Session, cohort_id: int, request: Request) -> Cohort:
    """Return cohort if user is owner or admin/data-manager, else 403."""
    user = _get_user(request)
    username = user.get("preferred_username", "")
    roles = user.get("roles", [])
    cohort = db.query(Cohort).filter(Cohort.id == cohort_id).first()
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")
    if cohort.created_by != username and not any(r in ("admin", "data-manager") for r in roles):
        raise HTTPException(status_code=403, detail="Only the owner or admin can manage sharing")
    return cohort


# ── Sharing endpoints ──

@router.post("/{cohort_id}/share")
def share_cohort(cohort_id: int, req: ShareRequest, request: Request, db: Session = Depends(get_db)):
    """Share a cohort with a user, a group, or everyone."""
    cohort = _require_owner_or_admin(db, cohort_id, request)
    user = _get_user(request)
    username = user.get("preferred_username", "")

    if req.share_type == "all":
        cohort.shared_with_all = 1
        db.commit()
        return {"cohort_id": cohort_id, "shared_with_all": True}

    if req.share_type not in ("user", "group"):
        raise HTTPException(status_code=400, detail="share_type must be 'user', 'group', or 'all'")
    if not req.share_target:
        raise HTTPException(status_code=400, detail="share_target is required for user/group sharing")

    # Validate target user has access to the cohort's CDM
    if req.share_type == "user" and req.share_target:
        has_acl = db.query(CdmAccess).filter(CdmAccess.cdm_name == cohort.cdm_name).first()
        if has_acl:
            target_access = db.query(CdmAccess).filter(
                CdmAccess.cdm_name == cohort.cdm_name,
                CdmAccess.username == req.share_target,
            ).first()
            if not target_access:
                raise HTTPException(
                    status_code=403,
                    detail=f"User '{req.share_target}' does not have access to CDM '{cohort.cdm_name}'",
                )

    # Validate group exists
    if req.share_type == "group":
        grp = db.query(UserGroup).filter(UserGroup.name == req.share_target).first()
        if not grp:
            raise HTTPException(status_code=404, detail=f"Group '{req.share_target}' not found")

    existing = db.query(CohortShare).filter(
        CohortShare.cohort_id == cohort_id,
        CohortShare.share_type == req.share_type,
        CohortShare.share_target == req.share_target,
    ).first()
    if existing:
        return {"cohort_id": cohort_id, "already_shared": True}

    share = CohortShare(
        cohort_id=cohort_id,
        share_type=req.share_type,
        share_target=req.share_target,
        shared_by=username,
    )
    db.add(share)

    # Notify recipients
    if req.share_type == "user":
        _notify(
            db, req.share_target, "cohort_shared",
            title=f"Cohorte partagée : {cohort.name}",
            message=f"{username} a partagé la cohorte « {cohort.name} » avec vous.",
            link=f"/cohorts?id={cohort_id}",
            item_id=str(cohort_id),
        )
    elif req.share_type == "group":
        # Notify every member of the group
        members = db.query(UserGroupMember).filter(UserGroupMember.group_name == req.share_target).all()
        for m in members:
            if m.username != username:  # don't notify the sharer
                _notify(
                    db, m.username, "cohort_shared",
                    title=f"Cohorte partagée : {cohort.name}",
                    message=f"{username} a partagé la cohorte « {cohort.name} » avec le groupe {req.share_target}.",
                    link=f"/cohorts?id={cohort_id}",
                    item_id=str(cohort_id),
                )

    db.commit()
    return {"cohort_id": cohort_id, "shared_with": {"type": req.share_type, "target": req.share_target}}


@router.post("/{cohort_id}/unshare")
def unshare_cohort(cohort_id: int, req: UnshareRequest, request: Request, db: Session = Depends(get_db)):
    """Remove sharing from a cohort."""
    cohort = _require_owner_or_admin(db, cohort_id, request)

    if req.share_type == "all":
        cohort.shared_with_all = 0
        db.commit()
        return {"cohort_id": cohort_id, "shared_with_all": False}

    deleted = db.query(CohortShare).filter(
        CohortShare.cohort_id == cohort_id,
        CohortShare.share_type == req.share_type,
        CohortShare.share_target == req.share_target,
    ).delete()
    db.commit()
    return {"cohort_id": cohort_id, "removed": deleted}


@router.get("/{cohort_id}/shares")
def list_cohort_shares(cohort_id: int, request: Request, db: Session = Depends(get_db)):
    """List all shares for a cohort."""
    cohort = _require_owner_or_admin(db, cohort_id, request)
    shares = db.query(CohortShare).filter(CohortShare.cohort_id == cohort_id).all()
    return {
        "cohort_id": cohort_id,
        "shared_with_all": bool(cohort.shared_with_all),
        "shares": [
            {"type": s.share_type, "target": s.share_target, "shared_by": s.shared_by,
             "created_at": s.created_at.isoformat() if s.created_at else None}
            for s in shares
        ],
    }


# ── Admin: cohorts per user ──

@router.get("/admin/by-user")
def admin_cohorts_by_user(
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Admin/data-manager only: list all cohorts grouped by creator.
    Also shows which cohorts each user has access to via sharing.
    """
    user = _get_user(request)
    roles = user.get("roles", [])
    if not any(r in ("admin", "data-manager") for r in roles):
        raise HTTPException(status_code=403, detail="Admin or data-manager only")

    cohorts = db.query(Cohort).order_by(Cohort.created_by, Cohort.updated_at.desc()).limit(limit).offset(offset).all()
    cohort_ids = [c.id for c in cohorts]
    shares = db.query(CohortShare).filter(CohortShare.cohort_id.in_(cohort_ids)).all() if cohort_ids else []

    # Build per-user view
    by_user: dict[str, dict] = {}
    for c in cohorts:
        creator = c.created_by or "unknown"
        if creator not in by_user:
            by_user[creator] = {"created": [], "shared_with": []}
        by_user[creator]["created"].append({
            "id": c.id, "name": c.name, "cdm_name": c.cdm_name,
            "shared_with_all": bool(c.shared_with_all),
        })

    # Track which cohorts are shared with which users
    for s in shares:
        if s.share_type == "user":
            target = s.share_target
            if target not in by_user:
                by_user[target] = {"created": [], "shared_with": []}
            by_user[target]["shared_with"].append({
                "cohort_id": s.cohort_id, "shared_by": s.shared_by,
            })

    return {"users": by_user}
