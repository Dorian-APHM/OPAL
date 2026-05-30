"""Tests for concept_set/router.py — Concept set CRUD endpoints."""
import pytest
import json


@pytest.fixture
def client():
    from tests.conftest import TestClient, app
    return TestClient(app)


@pytest.fixture
def concept_set_id(client):
    """Create a concept set and return its ID."""
    resp = client.post("/api/concept-sets/", json={
        "name": "Test Set",
        "cdm_name": "test_cdm",
        "domain": "Condition",
        "description": "A test concept set",
        "concepts": [
            {"concept_id": 201826, "include_descendants": True},
            {"concept_id": 316866, "include_descendants": False},
        ],
    })
    assert resp.status_code == 200
    return resp.json()["id"]


# ── CRUD tests ──

def test_create_concept_set(client):
    resp = client.post("/api/concept-sets/", json={
        "name": "My Set",
        "cdm_name": "cdm1",
        "concepts": [{"concept_id": 100}],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "My Set"
    assert "id" in data


def test_list_concept_sets(client, concept_set_id):
    # Listing is scoped to a CDM (security: no cross-CDM leak).
    resp = client.get("/api/concept-sets/?cdm_name=test_cdm")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["concept_sets"]) >= 1
    assert data["concept_sets"][0]["name"] == "Test Set"


def test_list_filter_by_cdm(client, concept_set_id):
    resp = client.get("/api/concept-sets/?cdm_name=test_cdm")
    assert resp.status_code == 200
    assert len(resp.json()["concept_sets"]) >= 1

    resp = client.get("/api/concept-sets/?cdm_name=nonexistent")
    assert resp.status_code == 200
    assert len(resp.json()["concept_sets"]) == 0


def test_list_filter_by_domain(client, concept_set_id):
    resp = client.get("/api/concept-sets/?cdm_name=test_cdm&domain=Condition")
    assert resp.status_code == 200
    assert len(resp.json()["concept_sets"]) >= 1


def test_get_concept_set(client, concept_set_id):
    resp = client.get(f"/api/concept-sets/{concept_set_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test Set"
    assert data["domain"] == "Condition"
    assert len(data["concepts"]) == 2


def test_get_nonexistent(client):
    resp = client.get("/api/concept-sets/99999")
    assert resp.status_code == 404


def test_update_concept_set(client, concept_set_id):
    resp = client.put(f"/api/concept-sets/{concept_set_id}", json={
        "name": "Updated Set",
        "description": "Updated description",
    }, headers={"X-Test-Username": "testuser"})
    assert resp.status_code == 200

    resp = client.get(f"/api/concept-sets/{concept_set_id}")
    assert resp.json()["name"] == "Updated Set"
    assert resp.json()["description"] == "Updated description"


def test_update_nonexistent(client):
    resp = client.put("/api/concept-sets/99999", json={"name": "X"})
    assert resp.status_code == 404


def test_update_wrong_user(client, concept_set_id):
    resp = client.put(
        f"/api/concept-sets/{concept_set_id}",
        json={"name": "Hacked"},
        headers={"X-Test-Username": "other_user", "X-Test-Roles": "chercheur"},
    )
    assert resp.status_code == 403


def test_delete_concept_set(client, concept_set_id):
    resp = client.delete(f"/api/concept-sets/{concept_set_id}",
                         headers={"X-Test-Username": "testuser"})
    assert resp.status_code == 200

    resp = client.get(f"/api/concept-sets/{concept_set_id}")
    assert resp.status_code == 404


def test_delete_nonexistent(client):
    resp = client.delete("/api/concept-sets/99999")
    assert resp.status_code == 404


def test_delete_wrong_user(client, concept_set_id):
    resp = client.delete(
        f"/api/concept-sets/{concept_set_id}",
        headers={"X-Test-Username": "other_user", "X-Test-Roles": "chercheur"},
    )
    assert resp.status_code == 403


def test_concept_count_field(client):
    """concept_count should reflect the number of concepts."""
    client.post("/api/concept-sets/", json={
        "name": "Three Concepts",
        "cdm_name": "cdm1",
        "concepts": [{"concept_id": 1}, {"concept_id": 2}, {"concept_id": 3}],
    })
    resp = client.get("/api/concept-sets/?cdm_name=cdm1")
    data = resp.json()
    found = [s for s in data["concept_sets"] if s["name"] == "Three Concepts"]
    assert found[0]["concept_count"] == 3
