"""Tests for Cohort Templates endpoints."""
import pytest


def test_list_templates(client):
    """Built-in templates should be auto-seeded."""
    resp = client.get("/api/cohort-templates/")
    assert resp.status_code == 200
    templates = resp.json()["templates"]
    assert len(templates) >= 5  # Built-in templates
    names = [t["name"] for t in templates]
    assert "Type 2 Diabetes" in names
    assert "Heart Failure" in names


def test_list_categories(client):
    resp = client.get("/api/cohort-templates/categories")
    assert resp.status_code == 200
    cats = resp.json()["categories"]
    assert "Cardiology" in cats
    assert "Endocrinology" in cats


def test_get_template(client):
    # List to get an ID
    templates = client.get("/api/cohort-templates/").json()["templates"]
    tid = templates[0]["id"]

    resp = client.get(f"/api/cohort-templates/{tid}")
    assert resp.status_code == 200
    assert "criteria_json" in resp.json()
    assert "inclusion" in resp.json()["criteria_json"]


def test_create_template(client):
    resp = client.post("/api/cohort-templates/", json={
        "name": "Custom Template",
        "category": "Research",
        "description": "Test template",
        "criteria_json": {
            "inclusion": {"operator": "AND", "criteria": [], "groups": []},
            "exclusion": {"operator": "OR", "criteria": [], "groups": []},
        },
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_delete_template(client):
    resp = client.post("/api/cohort-templates/", json={
        "name": "To Delete",
        "criteria_json": {"inclusion": {"operator": "AND", "criteria": []}},
    })
    tid = resp.json()["id"]

    resp = client.delete(f"/api/cohort-templates/{tid}")
    assert resp.status_code == 200


def test_filter_by_category(client):
    resp = client.get("/api/cohort-templates/", params={"category": "Cardiology"})
    assert resp.status_code == 200
    for t in resp.json()["templates"]:
        assert t["category"] == "Cardiology"


def test_get_nonexistent(client):
    resp = client.get("/api/cohort-templates/9999")
    assert resp.status_code == 404
