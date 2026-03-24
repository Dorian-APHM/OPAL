"""Tests for estimation/router.py — Population-level estimation endpoints.

KM endpoint requires OMOP connection (mocked).
CRUD endpoints use only app DB.
"""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    from tests.conftest import TestClient, app
    return TestClient(app)


@pytest.fixture
def cdm_name(client):
    """Create a test CDM and two cohorts for KM analysis."""
    client.post("/api/cdm/", json={
        "name": "est_test_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "testdb",
        "db_user": "user",
        "db_password": "pass",
        "omop_schema": "omop_cdm",
    })
    return "est_test_cdm"


# ── CRUD endpoints (app DB only) ──

def test_list_estimations_empty(client):
    resp = client.get("/api/estimation/")
    assert resp.status_code == 200
    assert resp.json()["analyses"] == []


def test_save_and_get_estimation(client, cdm_name):
    resp = client.post("/api/estimation/save", json={
        "cdm_name": cdm_name,
        "name": "Test KM",
        "analysis_type": "kaplan_meier",
        "target_cohort_id": 1,
        "outcome_cohort_id": 2,
        "parameters": {"time_unit": "days"},
        "results": {"survival_curve": [1.0, 0.9, 0.8]},
    })
    assert resp.status_code == 200
    analysis_id = resp.json()["id"]

    # Get by ID
    resp = client.get(f"/api/estimation/{analysis_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Test KM"

    # List
    resp = client.get(f"/api/estimation/?cdm_name={cdm_name}")
    assert resp.status_code == 200
    assert len(resp.json()["analyses"]) >= 1


def test_delete_estimation(client, cdm_name):
    resp = client.post("/api/estimation/save", json={
        "cdm_name": cdm_name,
        "name": "To Delete",
        "target_cohort_id": 1,
        "outcome_cohort_id": 2,
        "parameters": {},
        "results": {},
    })
    analysis_id = resp.json()["id"]

    resp = client.delete(f"/api/estimation/{analysis_id}")
    assert resp.status_code == 200

    resp = client.get(f"/api/estimation/{analysis_id}")
    assert resp.status_code == 404


def test_get_nonexistent_estimation(client):
    resp = client.get("/api/estimation/99999")
    assert resp.status_code == 404


def test_delete_nonexistent_estimation(client):
    resp = client.delete("/api/estimation/99999")
    assert resp.status_code == 404
