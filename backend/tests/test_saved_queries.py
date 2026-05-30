"""Tests for Saved Queries endpoints."""
import pytest


def test_list_queries_empty(client):
    resp = client.get("/api/saved-queries/")
    assert resp.status_code == 200
    assert resp.json()["queries"] == []


def test_create_query(client):
    resp = client.post("/api/saved-queries/", json={
        "cdm_name": "test_cdm",
        "name": "My Query",
        "sql": "SELECT * FROM person LIMIT 10",
        "description": "Test query",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    qid = resp.json()["id"]

    resp = client.get("/api/saved-queries/")
    queries = resp.json()["queries"]
    assert len(queries) == 1
    assert queries[0]["name"] == "My Query"
    assert queries[0]["sql"] == "SELECT * FROM person LIMIT 10"


def test_update_query(client):
    resp = client.post("/api/saved-queries/", json={
        "cdm_name": "test_cdm", "name": "Q1", "sql": "SELECT 1",
    })
    qid = resp.json()["id"]

    resp = client.put(f"/api/saved-queries/{qid}", json={
        "name": "Q1 Updated", "sql": "SELECT 2",
    })
    assert resp.status_code == 200

    resp = client.get("/api/saved-queries/")
    assert resp.json()["queries"][0]["name"] == "Q1 Updated"
    assert resp.json()["queries"][0]["sql"] == "SELECT 2"


def test_delete_query(client):
    resp = client.post("/api/saved-queries/", json={
        "cdm_name": "test_cdm", "name": "Q1", "sql": "SELECT 1",
    })
    qid = resp.json()["id"]

    resp = client.delete(f"/api/saved-queries/{qid}")
    assert resp.status_code == 200

    resp = client.get("/api/saved-queries/")
    assert len(resp.json()["queries"]) == 0


def test_filter_by_cdm(client):
    client.post("/api/saved-queries/", json={"cdm_name": "cdm_a", "name": "Q1", "sql": "SELECT 1"})
    client.post("/api/saved-queries/", json={"cdm_name": "cdm_b", "name": "Q2", "sql": "SELECT 2"})

    resp = client.get("/api/saved-queries/", params={"cdm_name": "cdm_a"})
    assert len(resp.json()["queries"]) == 1
    assert resp.json()["queries"][0]["name"] == "Q1"


def test_delete_nonexistent(client):
    resp = client.delete("/api/saved-queries/9999")
    assert resp.status_code == 404


def test_list_queries_isolated_per_user(client):
    """IDOR regression: a user must not see another user's saved queries."""
    # Alice saves a query.
    resp = client.post(
        "/api/saved-queries/",
        json={"cdm_name": "cdm_a", "name": "Alice secret", "sql": "SELECT 1"},
        headers={"X-Test-Username": "alice"},
    )
    assert resp.status_code == 200

    # Bob lists — must not see Alice's query.
    resp = client.get("/api/saved-queries/", headers={"X-Test-Username": "bob"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["queries"] == []
    assert body["total"] == 0

    # Alice still sees her own.
    resp = client.get("/api/saved-queries/", headers={"X-Test-Username": "alice"})
    names = [q["name"] for q in resp.json()["queries"]]
    assert names == ["Alice secret"]
