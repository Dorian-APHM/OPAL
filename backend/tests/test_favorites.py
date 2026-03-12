"""Tests for Favorites endpoints."""
import pytest


def test_list_favorites_empty(client):
    resp = client.get("/api/favorites/")
    assert resp.status_code == 200
    assert resp.json()["favorites"] == []


def test_add_favorite(client):
    resp = client.post("/api/favorites/", json={
        "item_type": "cohort",
        "item_id": "42",
        "item_label": "My Cohort",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    resp = client.get("/api/favorites/")
    favs = resp.json()["favorites"]
    assert len(favs) == 1
    assert favs[0]["item_type"] == "cohort"
    assert favs[0]["item_label"] == "My Cohort"


def test_add_duplicate(client):
    client.post("/api/favorites/", json={"item_type": "cohort", "item_id": "1", "item_label": "C"})
    resp = client.post("/api/favorites/", json={"item_type": "cohort", "item_id": "1", "item_label": "C"})
    assert resp.json()["status"] == "already_exists"


def test_remove_favorite(client):
    resp = client.post("/api/favorites/", json={"item_type": "concept", "item_id": "201826", "item_label": "T2D"})
    fav_id = resp.json()["id"]

    resp = client.delete(f"/api/favorites/{fav_id}")
    assert resp.status_code == 200

    resp = client.get("/api/favorites/")
    assert len(resp.json()["favorites"]) == 0


def test_filter_by_type(client):
    client.post("/api/favorites/", json={"item_type": "cohort", "item_id": "1", "item_label": "C1"})
    client.post("/api/favorites/", json={"item_type": "concept", "item_id": "100", "item_label": "X"})

    resp = client.get("/api/favorites/", params={"item_type": "cohort"})
    assert len(resp.json()["favorites"]) == 1
    assert resp.json()["favorites"][0]["item_type"] == "cohort"


def test_remove_nonexistent(client):
    resp = client.delete("/api/favorites/9999")
    assert resp.status_code == 404
