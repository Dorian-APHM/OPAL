"""
Cohort Templates endpoints.

Pre-defined cohort definitions that users can import and adapt.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.app_db import get_db
from db.models import CohortTemplate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cohort-templates", tags=["cohort-templates"])


# Built-in templates (loaded on first request)
BUILTIN_TEMPLATES = [
    {
        "name": "Type 2 Diabetes",
        "category": "Endocrinology",
        "description": "Patients with at least 2 condition occurrences of Type 2 Diabetes Mellitus (concept 201826) or descendants.",
        "criteria_json": {
            "inclusion": {
                "operator": "AND",
                "criteria": [
                    {
                        "id": "t2d-cond",
                        "domain": "Condition",
                        "concepts": [{"concept_id": 201826, "concept_name": "Type 2 diabetes mellitus", "concept_code": "44054006", "domain_id": "Condition", "vocabulary_id": "SNOMED", "concept_class_id": "Clinical Finding", "standard_concept": "S"}],
                        "include_descendants": True,
                        "source_codes": [],
                        "temporal": {"type": "any_time"},
                        "occurrence": {"type": "at_least", "count": 2},
                    }
                ],
                "groups": [],
            },
            "exclusion": {"operator": "OR", "criteria": [], "groups": []},
            "demographics": {},
        },
        "author": "OPAL",
    },
    {
        "name": "Heart Failure",
        "category": "Cardiology",
        "description": "Patients with at least 1 condition occurrence of Heart Failure (concept 316139) or descendants.",
        "criteria_json": {
            "inclusion": {
                "operator": "AND",
                "criteria": [
                    {
                        "id": "hf-cond",
                        "domain": "Condition",
                        "concepts": [{"concept_id": 316139, "concept_name": "Heart failure", "concept_code": "84114007", "domain_id": "Condition", "vocabulary_id": "SNOMED", "concept_class_id": "Clinical Finding", "standard_concept": "S"}],
                        "include_descendants": True,
                        "source_codes": [],
                        "temporal": {"type": "any_time"},
                        "occurrence": {"type": "at_least", "count": 1},
                    }
                ],
                "groups": [],
            },
            "exclusion": {"operator": "OR", "criteria": [], "groups": []},
            "demographics": {},
        },
        "author": "OPAL",
    },
    {
        "name": "Stroke (Cerebrovascular)",
        "category": "Neurology",
        "description": "Patients with cerebrovascular disease (concept 381591) — includes ischemic and hemorrhagic stroke.",
        "criteria_json": {
            "inclusion": {
                "operator": "AND",
                "criteria": [
                    {
                        "id": "stroke-cond",
                        "domain": "Condition",
                        "concepts": [{"concept_id": 381591, "concept_name": "Cerebrovascular disease", "concept_code": "62914000", "domain_id": "Condition", "vocabulary_id": "SNOMED", "concept_class_id": "Clinical Finding", "standard_concept": "S"}],
                        "include_descendants": True,
                        "source_codes": [],
                        "temporal": {"type": "any_time"},
                        "occurrence": {"type": "at_least", "count": 1},
                    }
                ],
                "groups": [],
            },
            "exclusion": {"operator": "OR", "criteria": [], "groups": []},
            "demographics": {},
        },
        "author": "OPAL",
    },
    {
        "name": "Hypertension",
        "category": "Cardiology",
        "description": "Patients with Essential Hypertension (concept 320128) or descendants, at least 2 occurrences.",
        "criteria_json": {
            "inclusion": {
                "operator": "AND",
                "criteria": [
                    {
                        "id": "htn-cond",
                        "domain": "Condition",
                        "concepts": [{"concept_id": 320128, "concept_name": "Essential hypertension", "concept_code": "59621000", "domain_id": "Condition", "vocabulary_id": "SNOMED", "concept_class_id": "Clinical Finding", "standard_concept": "S"}],
                        "include_descendants": True,
                        "source_codes": [],
                        "temporal": {"type": "any_time"},
                        "occurrence": {"type": "at_least", "count": 2},
                    }
                ],
                "groups": [],
            },
            "exclusion": {"operator": "OR", "criteria": [], "groups": []},
            "demographics": {},
        },
        "author": "OPAL",
    },
    {
        "name": "COVID-19",
        "category": "Infectious Disease",
        "description": "Patients with COVID-19 diagnosis (concept 37311061).",
        "criteria_json": {
            "inclusion": {
                "operator": "AND",
                "criteria": [
                    {
                        "id": "covid-cond",
                        "domain": "Condition",
                        "concepts": [{"concept_id": 37311061, "concept_name": "COVID-19", "concept_code": "840539006", "domain_id": "Condition", "vocabulary_id": "SNOMED", "concept_class_id": "Clinical Finding", "standard_concept": "S"}],
                        "include_descendants": True,
                        "source_codes": [],
                        "temporal": {"type": "any_time"},
                        "occurrence": {"type": "at_least", "count": 1},
                    }
                ],
                "groups": [],
            },
            "exclusion": {"operator": "OR", "criteria": [], "groups": []},
            "demographics": {},
        },
        "author": "OPAL",
    },
    {
        "name": "Pregnancy",
        "category": "Obstetrics",
        "description": "Patients with pregnancy-related conditions (concept 4299535 — Finding of pregnancy).",
        "criteria_json": {
            "inclusion": {
                "operator": "AND",
                "criteria": [
                    {
                        "id": "preg-cond",
                        "domain": "Condition",
                        "concepts": [{"concept_id": 4299535, "concept_name": "Finding related to pregnancy", "concept_code": "118185001", "domain_id": "Condition", "vocabulary_id": "SNOMED", "concept_class_id": "Clinical Finding", "standard_concept": "S"}],
                        "include_descendants": True,
                        "source_codes": [],
                        "temporal": {"type": "any_time"},
                        "occurrence": {"type": "at_least", "count": 1},
                    }
                ],
                "groups": [],
            },
            "exclusion": {"operator": "OR", "criteria": [], "groups": []},
            "demographics": {"gender": [8532]},
        },
        "author": "OPAL",
    },
]


def _ensure_builtins(db: Session):
    """Seed built-in templates if table is empty."""
    count = db.query(CohortTemplate).count()
    if count == 0:
        for t in BUILTIN_TEMPLATES:
            db.add(CohortTemplate(**t))
        db.commit()


@router.get("/")
def list_templates(
    category: str | None = None,
    db: Session = Depends(get_db),
):
    """List cohort templates."""
    _ensure_builtins(db)
    q = db.query(CohortTemplate)
    if category:
        q = q.filter(CohortTemplate.category == category)
    templates = q.order_by(CohortTemplate.category, CohortTemplate.name).all()
    return {
        "templates": [
            {
                "id": t.id,
                "name": t.name,
                "category": t.category,
                "description": t.description,
                "criteria_json": t.criteria_json,
                "author": t.author,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in templates
        ]
    }


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    """List distinct template categories."""
    _ensure_builtins(db)
    cats = db.query(CohortTemplate.category).distinct().all()
    return {"categories": sorted([c[0] for c in cats])}


@router.get("/{template_id}")
def get_template(template_id: int, db: Session = Depends(get_db)):
    """Get a single template."""
    t = db.query(CohortTemplate).filter(CohortTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return {
        "id": t.id,
        "name": t.name,
        "category": t.category,
        "description": t.description,
        "criteria_json": t.criteria_json,
        "author": t.author,
    }


class CreateTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    category: str = "General"
    description: str = ""
    criteria_json: dict


@router.post("/")
def create_template(req: CreateTemplateRequest, request: Request, db: Session = Depends(get_db)):
    """Create a new template (admin/data-manager)."""
    user = getattr(request.state, "user", {})
    t = CohortTemplate(
        name=req.name,
        category=req.category,
        description=req.description,
        criteria_json=req.criteria_json,
        author=user.get("preferred_username", "system"),
    )
    db.add(t)
    db.commit()
    return {"status": "ok", "id": t.id}


@router.delete("/{template_id}")
def delete_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    """Delete a template."""
    t = db.query(CohortTemplate).filter(CohortTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    user = getattr(request.state, "user", {})
    current_user = user.get("preferred_username", "system")
    if t.author != current_user:
        raise HTTPException(status_code=403, detail="Not authorized to delete this template")
    db.delete(t)
    db.commit()
    return {"status": "ok"}
