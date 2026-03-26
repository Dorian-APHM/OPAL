"""
Recent activity endpoint — returns the authenticated user's latest actions on a CDM.

Reads username directly from request.state.user (set by Keycloak middleware),
so no client-side username matching is needed.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import desc
from sqlalchemy.orm import Session

from db.app_db import get_db
from db.models import Cohort, MappingDecision

router = APIRouter(prefix="/api/recent", tags=["recent"])


@router.get("/{cdm_name}")
def get_recent(cdm_name: str, request: Request, db: Session = Depends(get_db)):
    """
    Return the 10 most recent actions for the authenticated user on the given CDM.

    Sources:
    - Cohorts created or last modified by the user
    - Mapping decisions made by the user

    Results are sorted by timestamp descending and capped at 10.
    """
    user_info = getattr(request.state, "user", {})
    username = user_info.get("preferred_username", "")

    items = []

    # --- Cohorts ---
    cohorts = (
        db.query(Cohort)
        .filter(Cohort.cdm_name == cdm_name, Cohort.created_by == username)
        .order_by(desc(Cohort.updated_at))
        .limit(20)
        .all()
    )
    for c in cohorts:
        ts = c.updated_at or c.created_at
        items.append({
            "type": "cohort",
            "label": c.name,
            "timestamp": ts.isoformat() if ts else None,
            "route": "/cohorts",
            "nav_state": {"openCohortId": c.id},
        })

    # --- Mapping decisions ---
    decisions = (
        db.query(MappingDecision)
        .filter(MappingDecision.cdm_name == cdm_name, MappingDecision.user == username)
        .order_by(desc(MappingDecision.created_at))
        .limit(20)
        .all()
    )
    for d in decisions:
        items.append({
            "type": "mapping",
            "label": f"{d.domain} — {d.source_value}",
            "timestamp": d.created_at.isoformat() if d.created_at else None,
            "route": "/mapping",
            "nav_state": None,
        })

    # Sort all by timestamp desc, keep top 10
    items = sorted(
        [i for i in items if i["timestamp"]],
        key=lambda x: x["timestamp"],
        reverse=True,
    )[:10]

    return {"items": items}
