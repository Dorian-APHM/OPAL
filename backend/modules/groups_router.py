"""
User group management endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.app_db import get_db
from db.models import UserGroup, UserGroupMember
from utils.notifications import notify as _notify

router = APIRouter(prefix="/api/groups", tags=["groups"])


class GroupCreateRequest(BaseModel):
    name: str
    description: str = ""
    members: list[str] = []  # list of usernames to add immediately


class GroupUpdateRequest(BaseModel):
    description: str | None = None
    members: list[str] | None = None  # if provided, replaces all members


class GroupMemberRequest(BaseModel):
    username: str


def _get_user(request: Request) -> dict:
    return getattr(request.state, "user", {})


@router.get("/")
def list_groups(db: Session = Depends(get_db)):
    """List all user groups with member counts."""
    groups = db.query(UserGroup).order_by(UserGroup.name).all()
    result = []
    for g in groups:
        count = db.query(UserGroupMember).filter(UserGroupMember.group_name == g.name).count()
        result.append({
            "name": g.name,
            "description": g.description,
            "created_by": g.created_by,
            "member_count": count,
            "created_at": g.created_at.isoformat() if g.created_at else None,
        })
    return {"groups": result}


@router.post("/")
def create_group(req: GroupCreateRequest, request: Request, db: Session = Depends(get_db)):
    """Create a user group."""
    user = _get_user(request)
    username = user.get("preferred_username", "system")

    existing = db.query(UserGroup).filter(UserGroup.name == req.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Group '{req.name}' already exists")

    group = UserGroup(name=req.name, description=req.description, created_by=username)
    db.add(group)

    for member in req.members:
        db.add(UserGroupMember(group_name=req.name, username=member, added_by=username))
        if member != username:
            _notify(
                db, member, "group_added",
                title=f"Ajouté au groupe : {req.name}",
                message=f"{username} vous a ajouté au groupe « {req.name} ».",
                item_id=req.name,
            )

    db.commit()
    return {"name": req.name, "members": req.members}


@router.get("/{group_name}")
def get_group(group_name: str, db: Session = Depends(get_db)):
    """Get a group with all its members."""
    group = db.query(UserGroup).filter(UserGroup.name == group_name).first()
    if not group:
        raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")

    members = db.query(UserGroupMember).filter(UserGroupMember.group_name == group_name).all()
    return {
        "name": group.name,
        "description": group.description,
        "created_by": group.created_by,
        "members": [{"username": m.username, "added_by": m.added_by} for m in members],
    }


@router.put("/{group_name}")
def update_group(group_name: str, req: GroupUpdateRequest, request: Request, db: Session = Depends(get_db)):
    """Update a group. If members list is provided, it replaces all current members."""
    user = _get_user(request)
    username = user.get("preferred_username", "system")

    group = db.query(UserGroup).filter(UserGroup.name == group_name).first()
    if not group:
        raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")

    if req.description is not None:
        group.description = req.description

    if req.members is not None:
        db.query(UserGroupMember).filter(UserGroupMember.group_name == group_name).delete()
        for member in req.members:
            db.add(UserGroupMember(group_name=group_name, username=member, added_by=username))

    db.commit()
    return {"name": group_name, "updated": True}


@router.delete("/{group_name}")
def delete_group(group_name: str, db: Session = Depends(get_db)):
    """Delete a group and all its members."""
    group = db.query(UserGroup).filter(UserGroup.name == group_name).first()
    if not group:
        raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")

    db.query(UserGroupMember).filter(UserGroupMember.group_name == group_name).delete()
    db.delete(group)
    db.commit()
    return {"deleted": True, "name": group_name}


@router.post("/{group_name}/members")
def add_member(group_name: str, req: GroupMemberRequest, request: Request, db: Session = Depends(get_db)):
    """Add a member to a group."""
    user = _get_user(request)
    username = user.get("preferred_username", "system")

    group = db.query(UserGroup).filter(UserGroup.name == group_name).first()
    if not group:
        raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")

    existing = db.query(UserGroupMember).filter(
        UserGroupMember.group_name == group_name,
        UserGroupMember.username == req.username,
    ).first()
    if existing:
        return {"already_member": True}

    db.add(UserGroupMember(group_name=group_name, username=req.username, added_by=username))
    if req.username != username:
        _notify(
            db, req.username, "group_added",
            title=f"Ajouté au groupe : {group_name}",
            message=f"{username} vous a ajouté au groupe « {group_name} ».",
            item_id=group_name,
        )
    db.commit()
    return {"added": req.username, "group": group_name}


@router.delete("/{group_name}/members/{member_username}")
def remove_member(group_name: str, member_username: str, db: Session = Depends(get_db)):
    """Remove a member from a group."""
    deleted = db.query(UserGroupMember).filter(
        UserGroupMember.group_name == group_name,
        UserGroupMember.username == member_username,
    ).delete()
    db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Member not found in group")
    return {"removed": member_username, "group": group_name}
