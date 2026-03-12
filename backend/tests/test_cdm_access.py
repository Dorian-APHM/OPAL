"""Tests for CDM Access Control endpoints."""
import pytest


def test_list_access_empty(client):
    resp = client.get("/api/cdm-access/")
    assert resp.status_code == 200
    assert resp.json()["grants"] == []
    assert resp.json()["group_grants"] == []


def test_grant_access(client):
    # First create a CDM
    client.post("/api/cdm/", json={
        "name": "test_cdm", "db_host": "localhost", "db_port": 5432,
        "db_name": "test_db", "db_user": "test_user", "db_password": "test_pass",
    })

    # Grant access
    resp = client.post("/api/cdm-access/grant", json={
        "cdm_name": "test_cdm", "username": "researcher1",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # List should show the grant
    resp = client.get("/api/cdm-access/", params={"cdm_name": "test_cdm"})
    assert len(resp.json()["grants"]) == 1
    assert resp.json()["grants"][0]["username"] == "researcher1"


def test_grant_duplicate(client):
    client.post("/api/cdm/", json={
        "name": "test_cdm", "db_host": "localhost", "db_port": 5432,
        "db_name": "test_db", "db_user": "test_user", "db_password": "test_pass",
    })
    client.post("/api/cdm-access/grant", json={"cdm_name": "test_cdm", "username": "u1"})
    resp = client.post("/api/cdm-access/grant", json={"cdm_name": "test_cdm", "username": "u1"})
    assert resp.json()["status"] == "already_granted"


def test_revoke_access(client):
    client.post("/api/cdm/", json={
        "name": "test_cdm", "db_host": "localhost", "db_port": 5432,
        "db_name": "test_db", "db_user": "test_user", "db_password": "test_pass",
    })
    client.post("/api/cdm-access/grant", json={"cdm_name": "test_cdm", "username": "u1"})
    resp = client.post("/api/cdm-access/revoke", json={"cdm_name": "test_cdm", "username": "u1"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Should be empty now
    resp = client.get("/api/cdm-access/", params={"cdm_name": "test_cdm"})
    assert len(resp.json()["grants"]) == 0


def test_grant_nonexistent_cdm(client):
    resp = client.post("/api/cdm-access/grant", json={
        "cdm_name": "nonexistent", "username": "u1",
    })
    assert resp.status_code == 404


def test_get_accessible_cdms(client):
    """Admin user should see all CDMs."""
    client.post("/api/cdm/", json={
        "name": "cdm_a", "db_host": "localhost", "db_port": 5432,
        "db_name": "a", "db_user": "u", "db_password": "p",
    })
    resp = client.get("/api/cdm-access/cdms-for-user")
    assert resp.status_code == 200
    assert "cdm_a" in resp.json()["cdms"]


def test_clear_cdm_access(client):
    client.post("/api/cdm/", json={
        "name": "test_cdm", "db_host": "localhost", "db_port": 5432,
        "db_name": "test_db", "db_user": "test_user", "db_password": "test_pass",
    })
    client.post("/api/cdm-access/grant", json={"cdm_name": "test_cdm", "username": "u1"})
    client.post("/api/cdm-access/grant", json={"cdm_name": "test_cdm", "username": "u2"})
    resp = client.delete("/api/cdm-access/cdm/test_cdm")
    assert resp.json()["deleted_users"] == 2
    assert resp.json()["deleted_groups"] == 0


# ── Group access tests ──


def test_grant_group_access(client):
    # Create CDM
    client.post("/api/cdm/", json={
        "name": "test_cdm", "db_host": "localhost", "db_port": 5432,
        "db_name": "test_db", "db_user": "test_user", "db_password": "test_pass",
    })
    # Create group
    client.post("/api/groups/", json={"name": "researchers", "members": ["alice", "bob"]})

    # Grant group access
    resp = client.post("/api/cdm-access/grant-group", json={
        "cdm_name": "test_cdm", "group_name": "researchers",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # List should show the group grant
    resp = client.get("/api/cdm-access/")
    assert len(resp.json()["group_grants"]) == 1
    assert resp.json()["group_grants"][0]["group_name"] == "researchers"


def test_grant_group_duplicate(client):
    client.post("/api/cdm/", json={
        "name": "test_cdm", "db_host": "localhost", "db_port": 5432,
        "db_name": "test_db", "db_user": "test_user", "db_password": "test_pass",
    })
    client.post("/api/groups/", json={"name": "team1"})
    client.post("/api/cdm-access/grant-group", json={"cdm_name": "test_cdm", "group_name": "team1"})
    resp = client.post("/api/cdm-access/grant-group", json={"cdm_name": "test_cdm", "group_name": "team1"})
    assert resp.json()["status"] == "already_granted"


def test_grant_group_nonexistent_group(client):
    client.post("/api/cdm/", json={
        "name": "test_cdm", "db_host": "localhost", "db_port": 5432,
        "db_name": "test_db", "db_user": "test_user", "db_password": "test_pass",
    })
    resp = client.post("/api/cdm-access/grant-group", json={
        "cdm_name": "test_cdm", "group_name": "nonexistent",
    })
    assert resp.status_code == 404


def test_revoke_group_access(client):
    client.post("/api/cdm/", json={
        "name": "test_cdm", "db_host": "localhost", "db_port": 5432,
        "db_name": "test_db", "db_user": "test_user", "db_password": "test_pass",
    })
    client.post("/api/groups/", json={"name": "team1"})
    client.post("/api/cdm-access/grant-group", json={"cdm_name": "test_cdm", "group_name": "team1"})

    resp = client.post("/api/cdm-access/revoke-group", json={
        "cdm_name": "test_cdm", "group_name": "team1",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Group grants should be empty
    resp = client.get("/api/cdm-access/")
    assert len(resp.json()["group_grants"]) == 0


def test_clear_cdm_access_includes_groups(client):
    client.post("/api/cdm/", json={
        "name": "test_cdm", "db_host": "localhost", "db_port": 5432,
        "db_name": "test_db", "db_user": "test_user", "db_password": "test_pass",
    })
    client.post("/api/groups/", json={"name": "team1"})
    client.post("/api/cdm-access/grant", json={"cdm_name": "test_cdm", "username": "u1"})
    client.post("/api/cdm-access/grant-group", json={"cdm_name": "test_cdm", "group_name": "team1"})

    resp = client.delete("/api/cdm-access/cdm/test_cdm")
    assert resp.json()["deleted_users"] == 1
    assert resp.json()["deleted_groups"] == 1
