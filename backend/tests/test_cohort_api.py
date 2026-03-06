"""
Tests for the cohort module API endpoints.
Uses the shared conftest.py fixtures for database setup.
"""
import pytest


@pytest.fixture
def cdm_name(client):
    """Create a test CDM and return its name."""
    client.post("/api/cdm/", json={
        "name": "test_cdm",
        "db_host": "localhost",
        "db_port": 5432,
        "db_name": "testdb",
        "db_user": "user",
        "db_password": "pass",
        "omop_schema": "omop_cdm",
    })
    return "test_cdm"


# ──── Cohort CRUD tests ────

def test_list_cohorts_empty(client):
    resp = client.get("/api/cohorts/")
    assert resp.status_code == 200
    assert resp.json()["cohorts"] == []


def test_create_cohort(client, cdm_name):
    resp = client.post("/api/cohorts/", json={
        "cdm_name": cdm_name,
        "name": "Test Cohort",
        "description": "A test cohort",
        "criteria": {
            "inclusion": {
                "operator": "AND",
                "criteria": [
                    {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}}
                ],
            },
            "exclusion": {"operator": "OR", "criteria": []},
        },
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test Cohort"
    assert data["version"] == 1
    assert "generated_sql" in data
    assert "condition_occurrence" in data["generated_sql"]


def test_create_cohort_unknown_cdm(client):
    resp = client.post("/api/cohorts/", json={
        "cdm_name": "nonexistent",
        "name": "Test",
        "criteria": {"inclusion": {"operator": "AND", "criteria": []}, "exclusion": {"operator": "OR", "criteria": []}},
    })
    assert resp.status_code == 404


def test_create_cohort_invalid_domain(client, cdm_name):
    resp = client.post("/api/cohorts/", json={
        "cdm_name": cdm_name,
        "name": "Bad Cohort",
        "criteria": {
            "inclusion": {
                "operator": "AND",
                "criteria": [
                    {"domain": "FakeDomain", "concepts": [1], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}}
                ],
            },
        },
    })
    assert resp.status_code == 400
    assert "Invalid criteria" in resp.json()["detail"]


def test_get_cohort(client, cdm_name):
    create_resp = client.post("/api/cohorts/", json={
        "cdm_name": cdm_name,
        "name": "My Cohort",
        "criteria": {
            "inclusion": {
                "operator": "AND",
                "criteria": [
                    {"domain": "Drug", "concepts": [1503297], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}}
                ],
            },
        },
    })
    cohort_id = create_resp.json()["id"]

    resp = client.get(f"/api/cohorts/{cohort_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "My Cohort"
    assert data["cdm_name"] == cdm_name
    assert len(data["versions"]) == 1
    assert data["versions"][0]["version"] == 1


def test_get_cohort_not_found(client):
    resp = client.get("/api/cohorts/9999")
    assert resp.status_code == 404


def test_update_cohort_name(client, cdm_name):
    create_resp = client.post("/api/cohorts/", json={
        "cdm_name": cdm_name,
        "name": "Original",
        "criteria": {
            "inclusion": {
                "operator": "AND",
                "criteria": [
                    {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}}
                ],
            },
        },
    })
    cohort_id = create_resp.json()["id"]

    resp = client.put(f"/api/cohorts/{cohort_id}", json={"name": "Updated Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"
    assert resp.json()["new_version"] is None  # No new version for name-only change


def test_update_cohort_criteria_creates_new_version(client, cdm_name):
    create_resp = client.post("/api/cohorts/", json={
        "cdm_name": cdm_name,
        "name": "Versioned",
        "criteria": {
            "inclusion": {
                "operator": "AND",
                "criteria": [
                    {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}}
                ],
            },
        },
    })
    cohort_id = create_resp.json()["id"]

    # Update with new criteria
    resp = client.put(f"/api/cohorts/{cohort_id}", json={
        "criteria": {
            "inclusion": {
                "operator": "AND",
                "criteria": [
                    {"domain": "Drug", "concepts": [1503297], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}}
                ],
            },
        },
    })
    assert resp.status_code == 200
    assert resp.json()["new_version"] == 2

    # Verify two versions
    detail_resp = client.get(f"/api/cohorts/{cohort_id}")
    assert len(detail_resp.json()["versions"]) == 2


def test_delete_cohort(client, cdm_name):
    create_resp = client.post("/api/cohorts/", json={
        "cdm_name": cdm_name,
        "name": "To Delete",
        "criteria": {
            "inclusion": {
                "operator": "AND",
                "criteria": [
                    {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}}
                ],
            },
        },
    })
    cohort_id = create_resp.json()["id"]

    resp = client.delete(f"/api/cohorts/{cohort_id}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    # Verify deleted
    get_resp = client.get(f"/api/cohorts/{cohort_id}")
    assert get_resp.status_code == 404


def test_delete_nonexistent_cohort(client):
    resp = client.delete("/api/cohorts/9999")
    assert resp.status_code == 404


def test_list_cohorts_filtered_by_cdm(client, cdm_name):
    client.post("/api/cohorts/", json={
        "cdm_name": cdm_name,
        "name": "Cohort A",
        "criteria": {
            "inclusion": {"operator": "AND", "criteria": [
                {"domain": "Condition", "concepts": [1], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}}
            ]},
        },
    })

    resp = client.get(f"/api/cohorts/?cdm_name={cdm_name}")
    assert resp.status_code == 200
    assert len(resp.json()["cohorts"]) == 1

    resp2 = client.get("/api/cohorts/?cdm_name=other_cdm")
    assert len(resp2.json()["cohorts"]) == 0


def test_list_cohort_domains(client):
    resp = client.get("/api/cohorts/domains")
    assert resp.status_code == 200
    domains = resp.json()["domains"]
    names = [d["name"] for d in domains]
    assert "Condition" in names
    assert "Drug" in names
    assert "Measurement" in names


# ──── Export tests ────

def test_export_sql(client, cdm_name):
    create_resp = client.post("/api/cohorts/", json={
        "cdm_name": cdm_name,
        "name": "Export Test",
        "criteria": {
            "inclusion": {"operator": "AND", "criteria": [
                {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}}
            ]},
        },
    })
    cohort_id = create_resp.json()["id"]

    resp = client.get(f"/api/cohorts/{cohort_id}/export?format=sql")
    assert resp.status_code == 200
    assert "condition_occurrence" in resp.text


def test_export_nonexistent(client):
    resp = client.get("/api/cohorts/9999/export?format=sql")
    assert resp.status_code == 404
