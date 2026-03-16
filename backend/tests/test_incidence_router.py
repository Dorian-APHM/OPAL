"""Tests for incidence/router.py — Incidence rate analysis endpoints.

Compute endpoint requires OMOP connection (mocked).
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
    client.post("/api/cdm/", json={
        "name": "inc_test_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "testdb",
        "db_user": "user",
        "db_password": "pass",
        "omop_schema": "omop_cdm",
    })
    return "inc_test_cdm"


# ── CRUD endpoints (app DB only) ──

def test_list_analyses_empty(client):
    resp = client.get("/api/incidence/")
    assert resp.status_code == 200
    assert resp.json()["analyses"] == []


def test_save_and_get_analysis(client, cdm_name):
    resp = client.post("/api/incidence/save", json={
        "cdm_name": cdm_name,
        "name": "Test Incidence",
        "target_cohort_id": 1,
        "outcome_cohort_id": 2,
        "parameters": {"time_at_risk_start": 0, "time_at_risk_end": "observation_end"},
        "results": {"incidence_rate": 0.05, "cases": 50, "person_years": 1000},
    })
    assert resp.status_code == 200
    analysis_id = resp.json()["id"]

    resp = client.get(f"/api/incidence/{analysis_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Test Incidence"

    resp = client.get(f"/api/incidence/?cdm_name={cdm_name}")
    assert resp.status_code == 200
    assert len(resp.json()["analyses"]) >= 1


def test_delete_analysis(client, cdm_name):
    resp = client.post("/api/incidence/save", json={
        "cdm_name": cdm_name,
        "name": "Delete Me",
        "target_cohort_id": 1,
        "outcome_cohort_id": 2,
        "parameters": {},
        "results": {},
    })
    analysis_id = resp.json()["id"]

    resp = client.delete(f"/api/incidence/{analysis_id}")
    assert resp.status_code == 200

    resp = client.get(f"/api/incidence/{analysis_id}")
    assert resp.status_code == 404


def test_get_nonexistent(client):
    resp = client.get("/api/incidence/99999")
    assert resp.status_code == 404


def test_delete_nonexistent(client):
    resp = client.delete("/api/incidence/99999")
    assert resp.status_code == 404
