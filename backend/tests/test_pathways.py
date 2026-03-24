"""
Tests for the pathways analysis module.
Tests the API endpoints (validation) and the pure-Python aggregation logic.
"""
import pytest
from unittest.mock import MagicMock, patch
from collections import defaultdict


@pytest.fixture
def cdm_name(client):
    """Create a test CDM and return its name."""
    client.post("/api/cdm/", json={
        "name": "pw_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "testdb",
        "db_user": "user",
        "db_password": "pass",
        "omop_schema": "omop_cdm",
    })
    return "pw_cdm"


# ──── API validation tests ────

def test_pathways_missing_event_cohorts(client, cdm_name):
    """Pathways request must have at least 1 event cohort."""
    resp = client.post("/api/cohorts/pathways", json={
        "cdm_name": cdm_name,
        "criteria": {
            "inclusion": {"operator": "AND", "criteria": [
                {"domain": "Condition", "concepts": [201826],
                 "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
            ]},
        },
        "event_cohorts": [],
    })
    assert resp.status_code == 422  # Validation error: min_items=1


def test_pathways_missing_criteria_fields(client, cdm_name):
    """Event cohort must have required fields."""
    resp = client.post("/api/cohorts/pathways", json={
        "cdm_name": cdm_name,
        "criteria": {
            "inclusion": {"operator": "AND", "criteria": []},
        },
        "event_cohorts": [
            {"name": "", "domain": "Drug", "concept_ids": [1]},  # empty name
        ],
    })
    assert resp.status_code == 422


def test_pathways_max_depth_validation(client, cdm_name):
    """max_depth must be between 1 and 10."""
    resp = client.post("/api/cohorts/pathways", json={
        "cdm_name": cdm_name,
        "criteria": {
            "inclusion": {"operator": "AND", "criteria": []},
        },
        "event_cohorts": [
            {"name": "Drug A", "domain": "Drug", "concept_ids": [1234]},
        ],
        "max_depth": 50,
    })
    assert resp.status_code == 422


def test_pathways_unknown_cdm(client):
    """Unknown CDM should return 404."""
    resp = client.post("/api/cohorts/pathways", json={
        "cdm_name": "nonexistent",
        "criteria": {
            "inclusion": {"operator": "AND", "criteria": []},
        },
        "event_cohorts": [
            {"name": "Drug A", "domain": "Drug", "concept_ids": [1234]},
        ],
    })
    assert resp.status_code == 404


def test_pathways_status_unknown_task(client):
    """Unknown task_id should return 404."""
    resp = client.get("/api/cohorts/pathways/status/unknown-uuid")
    assert resp.status_code == 404


def test_pathways_cancel_unknown_task(client):
    """Unknown task_id cancel should return 404."""
    resp = client.post("/api/cohorts/pathways/cancel/unknown-uuid")
    assert resp.status_code == 404


# ──── Sunburst tree builder tests ────

def test_build_sunburst_tree_basic():
    """Test that the sunburst tree builder produces correct structure."""
    from modules.cohort.pathways import _build_sunburst_tree

    person_paths = {
        1: ["Drug A", "Drug B"],
        2: ["Drug A", "Drug B"],
        3: ["Drug A", "Drug C"],
        4: ["Drug B"],
        5: ["Drug A"],
    }
    tree = _build_sunburst_tree(person_paths, min_cell_count=1, target_size=5)

    assert tree["name"] == "Target"
    assert tree["count"] == 5
    assert tree["pct"] == 100.0

    # First ring: Drug A (4 persons) and Drug B (1 person)
    children = tree["children"]
    names = {c["name"]: c for c in children}
    assert "Drug A" in names
    assert "Drug B" in names
    assert names["Drug A"]["count"] == 4
    assert names["Drug B"]["count"] == 1


def test_build_sunburst_tree_min_cell_count():
    """Nodes below min_cell_count should be pruned."""
    from modules.cohort.pathways import _build_sunburst_tree

    person_paths = {
        1: ["Drug A"],
        2: ["Drug A"],
        3: ["Drug A"],
        4: ["Drug B"],  # Only 1 person → should be pruned with min_cell_count=2
    }
    tree = _build_sunburst_tree(person_paths, min_cell_count=2, target_size=4)

    children = tree["children"]
    names = [c["name"] for c in children]
    assert "Drug A" in names
    assert "Drug B" not in names


def test_build_sunburst_tree_nested():
    """Test correct nesting of multi-step pathways."""
    from modules.cohort.pathways import _build_sunburst_tree

    person_paths = {
        1: ["A", "B", "C"],
        2: ["A", "B", "D"],
        3: ["A", "B", "C"],
    }
    tree = _build_sunburst_tree(person_paths, min_cell_count=1, target_size=3)

    # Root → A (3) → B (3) → C (2), D (1)
    a_node = tree["children"][0]
    assert a_node["name"] == "A"
    assert a_node["count"] == 3

    b_node = a_node["children"][0]
    assert b_node["name"] == "B"
    assert b_node["count"] == 3

    c_d = {c["name"]: c["count"] for c in b_node["children"]}
    assert c_d["C"] == 2
    assert c_d["D"] == 1


def test_build_sunburst_tree_empty():
    """Empty person_paths should return a root-only tree."""
    from modules.cohort.pathways import _build_sunburst_tree

    tree = _build_sunburst_tree({}, min_cell_count=1, target_size=0)
    assert tree["name"] == "Target"
    assert tree["count"] == 0
    assert tree["children"] == []


def test_prune_and_compute_pct():
    """Test percentage computation."""
    from modules.cohort.pathways import _prune_and_compute_pct

    node = {
        "name": "Root",
        "count": 100,
        "pct": 0,
        "children": [
            {"name": "A", "count": 60, "pct": 0, "children": []},
            {"name": "B", "count": 40, "pct": 0, "children": []},
            {"name": "C", "count": 3, "pct": 0, "children": []},  # Should be pruned
        ],
    }
    _prune_and_compute_pct(node, total=100, min_count=5)

    assert node["pct"] == 100.0
    assert len(node["children"]) == 2  # C pruned
    assert node["children"][0]["name"] == "A"
    assert node["children"][0]["pct"] == 60.0
    assert node["children"][1]["name"] == "B"
    assert node["children"][1]["pct"] == 40.0
