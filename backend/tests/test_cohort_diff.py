"""Tests for Cohort Version Diff endpoint."""
import pytest

from db.models import Cohort, CohortVersion


def _create_cohort_with_versions(db):
    """Create a cohort with 2 versions for testing."""
    cohort = Cohort(cdm_name="test_cdm", name="Test Cohort")
    db.add(cohort)
    db.commit()
    db.refresh(cohort)

    v1 = CohortVersion(
        cohort_id=cohort.id, version=1,
        criteria_json={
            "inclusion": {
                "operator": "AND",
                "criteria": [
                    {"id": "c1", "domain": "Condition", "concepts": [{"concept_id": 201826, "concept_name": "T2D"}],
                     "include_descendants": True, "source_codes": [], "temporal": {"type": "any_time"},
                     "occurrence": {"type": "at_least", "count": 1}},
                ],
                "groups": [],
            },
            "exclusion": {"operator": "OR", "criteria": [], "groups": []},
            "demographics": {},
        },
        patient_count=1000,
    )
    v2 = CohortVersion(
        cohort_id=cohort.id, version=2,
        criteria_json={
            "inclusion": {
                "operator": "AND",
                "criteria": [
                    {"id": "c1", "domain": "Condition", "concepts": [{"concept_id": 201826, "concept_name": "T2D"}],
                     "include_descendants": True, "source_codes": [], "temporal": {"type": "any_time"},
                     "occurrence": {"type": "at_least", "count": 2}},  # changed count
                    {"id": "c2", "domain": "Drug", "concepts": [{"concept_id": 1234, "concept_name": "Metformin"}],
                     "include_descendants": False, "source_codes": [], "temporal": {"type": "any_time"},
                     "occurrence": {"type": "at_least", "count": 1}},  # new criterion
                ],
                "groups": [],
            },
            "exclusion": {"operator": "OR", "criteria": [], "groups": []},
            "demographics": {"gender": [8507]},
        },
        patient_count=750,
    )
    db.add(v1)
    db.add(v2)
    db.commit()
    return cohort.id


def test_diff_versions(client):
    from tests.conftest import TestSession
    db = TestSession()
    cohort_id = _create_cohort_with_versions(db)
    db.close()

    resp = client.get(f"/api/cohorts/{cohort_id}/diff", params={"version_a": 1, "version_b": 2})
    assert resp.status_code == 200
    data = resp.json()

    assert data["patient_count_a"] == 1000
    assert data["patient_count_b"] == 750
    assert data["patient_count_delta"] == -250
    assert data["patient_count_pct_change"] == -25.0

    diffs = data["diffs"]
    assert len(diffs) >= 2  # At least: c1 modified + c2 added

    # Check that c1 was detected as modified
    modified = [d for d in diffs if d["type"] == "modified" and d.get("criterion_id") == "c1"]
    assert len(modified) == 1
    assert "occurrence changed" in modified[0]["detail"]

    # Check that c2 was detected as added
    added = [d for d in diffs if d["type"] == "added"]
    assert len(added) >= 1

    # Check demographics changed
    demo_diffs = [d for d in diffs if d["section"] == "demographics"]
    assert len(demo_diffs) == 1


def test_diff_nonexistent_cohort(client):
    resp = client.get("/api/cohorts/9999/diff", params={"version_a": 1, "version_b": 2})
    assert resp.status_code == 404


def test_diff_nonexistent_version(client):
    from tests.conftest import TestSession
    db = TestSession()
    cohort = Cohort(cdm_name="test_cdm", name="C")
    db.add(cohort)
    db.commit()
    cid = cohort.id
    db.close()

    resp = client.get(f"/api/cohorts/{cid}/diff", params={"version_a": 1, "version_b": 2})
    assert resp.status_code == 404
