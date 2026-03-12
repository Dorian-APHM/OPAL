"""Tests for Notifications endpoints."""
import pytest


def test_list_notifications_empty(client):
    resp = client.get("/api/notifications/")
    assert resp.status_code == 200
    assert resp.json()["notifications"] == []


def test_create_and_list(client):
    # Create a notification
    resp = client.post("/api/notifications/create", json={
        "username": "testuser",
        "type": "mapping_review",
        "title": "New mapping to review",
        "message": "5 new suggestions",
        "link": "/mapping",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    notif_id = resp.json()["id"]

    # List (current user is testuser from conftest)
    resp = client.get("/api/notifications/")
    assert len(resp.json()["notifications"]) == 1
    assert resp.json()["notifications"][0]["type"] == "mapping_review"
    assert resp.json()["notifications"][0]["read"] is False


def test_badges(client):
    # Create notifications of different types
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "mapping_review", "title": "T1",
    })
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "mapping_review", "title": "T2",
    })
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done", "title": "Q1",
    })

    resp = client.get("/api/notifications/badges")
    assert resp.status_code == 200
    badges = resp.json()["badges"]
    assert badges.get("mapping") == 2
    assert badges.get("quality") == 1
    assert resp.json()["total"] == 3


def test_mark_as_read(client):
    resp = client.post("/api/notifications/create", json={
        "username": "testuser", "type": "cohort_shared", "title": "Shared",
    })
    nid = resp.json()["id"]

    # Mark read
    resp = client.post(f"/api/notifications/{nid}/read")
    assert resp.status_code == 200

    # Badges should be 0
    resp = client.get("/api/notifications/badges")
    assert resp.json()["total"] == 0


def test_mark_all_read(client):
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "mapping_review", "title": "T1",
    })
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "mapping_review", "title": "T2",
    })

    resp = client.post("/api/notifications/read-all", params={"notif_type": "mapping_review"})
    assert resp.status_code == 200

    resp = client.get("/api/notifications/badges")
    assert resp.json()["total"] == 0


def test_unread_only_filter(client):
    client.post("/api/notifications/create", json={
        "username": "testuser", "type": "quality_done", "title": "Done",
    })
    nid = client.get("/api/notifications/").json()["notifications"][0]["id"]
    client.post(f"/api/notifications/{nid}/read")

    # Unread only should be empty
    resp = client.get("/api/notifications/", params={"unread_only": True})
    assert len(resp.json()["notifications"]) == 0

    # All should still have 1
    resp = client.get("/api/notifications/")
    assert len(resp.json()["notifications"]) == 1
