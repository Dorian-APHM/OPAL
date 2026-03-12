"""Tests for user group management."""
import pytest
from db.models import Notification


def test_create_group(client):
    resp = client.post("/api/groups/", json={
        "name": "team_data", "description": "Data team", "members": ["alice", "bob"],
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "team_data"
    assert resp.json()["members"] == ["alice", "bob"]


def test_create_group_duplicate(client):
    client.post("/api/groups/", json={"name": "dup_group"})
    resp = client.post("/api/groups/", json={"name": "dup_group"})
    assert resp.status_code == 409


def test_list_groups(client):
    client.post("/api/groups/", json={"name": "grp_a", "members": ["u1"]})
    client.post("/api/groups/", json={"name": "grp_b", "members": ["u1", "u2"]})
    resp = client.get("/api/groups/")
    assert resp.status_code == 200
    groups = {g["name"]: g for g in resp.json()["groups"]}
    assert groups["grp_a"]["member_count"] == 1
    assert groups["grp_b"]["member_count"] == 2


def test_get_group(client):
    client.post("/api/groups/", json={"name": "detail_grp", "members": ["alice"]})
    resp = client.get("/api/groups/detail_grp")
    assert resp.status_code == 200
    assert resp.json()["name"] == "detail_grp"
    assert len(resp.json()["members"]) == 1
    assert resp.json()["members"][0]["username"] == "alice"


def test_get_group_not_found(client):
    resp = client.get("/api/groups/nonexistent")
    assert resp.status_code == 404


def test_update_group_replace_members(client):
    client.post("/api/groups/", json={"name": "upd_grp", "members": ["alice", "bob"]})
    resp = client.put("/api/groups/upd_grp", json={"members": ["charlie"]})
    assert resp.status_code == 200

    detail = client.get("/api/groups/upd_grp")
    members = [m["username"] for m in detail.json()["members"]]
    assert members == ["charlie"]


def test_delete_group(client):
    client.post("/api/groups/", json={"name": "del_grp"})
    resp = client.delete("/api/groups/del_grp")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    get_resp = client.get("/api/groups/del_grp")
    assert get_resp.status_code == 404


def test_add_member(client):
    client.post("/api/groups/", json={"name": "add_grp"})
    resp = client.post("/api/groups/add_grp/members", json={"username": "newuser"})
    assert resp.status_code == 200
    assert resp.json()["added"] == "newuser"

    detail = client.get("/api/groups/add_grp")
    assert len(detail.json()["members"]) == 1


def test_add_member_duplicate(client):
    client.post("/api/groups/", json={"name": "dup_mem_grp", "members": ["alice"]})
    resp = client.post("/api/groups/dup_mem_grp/members", json={"username": "alice"})
    assert resp.status_code == 200
    assert resp.json()["already_member"] is True


def test_remove_member(client):
    client.post("/api/groups/", json={"name": "rm_grp", "members": ["alice", "bob"]})
    resp = client.delete("/api/groups/rm_grp/members/alice")
    assert resp.status_code == 200

    detail = client.get("/api/groups/rm_grp")
    members = [m["username"] for m in detail.json()["members"]]
    assert "alice" not in members
    assert "bob" in members


def test_remove_member_not_found(client):
    client.post("/api/groups/", json={"name": "rm_nf_grp"})
    resp = client.delete("/api/groups/rm_nf_grp/members/ghost")
    assert resp.status_code == 404


# ── Notifications ──

def _get_db():
    from tests.conftest import TestSession
    return TestSession()


def test_create_group_notifies_members(client):
    """Creating a group with members notifies them (except the creator)."""
    client.post("/api/groups/", json={"name": "notif_grp", "members": ["alice", "bob"]})

    db = _get_db()
    try:
        notifs = db.query(Notification).filter(Notification.type == "group_added").all()
        usernames = {n.username for n in notifs}
        assert "alice" in usernames
        assert "bob" in usernames
        # testuser (creator) should NOT be notified
        assert "testuser" not in usernames
    finally:
        db.close()


def test_add_member_notifies(client):
    """Adding a member to a group notifies them."""
    client.post("/api/groups/", json={"name": "add_notif_grp"})
    client.post("/api/groups/add_notif_grp/members", json={"username": "charlie"})

    db = _get_db()
    try:
        notifs = db.query(Notification).filter(
            Notification.username == "charlie", Notification.type == "group_added"
        ).all()
        assert len(notifs) == 1
        assert "add_notif_grp" in notifs[0].title
    finally:
        db.close()


def test_add_self_no_notification(client):
    """Adding yourself to a group should not create a notification."""
    client.post("/api/groups/", json={"name": "self_grp"})
    client.post("/api/groups/self_grp/members", json={"username": "testuser"})

    db = _get_db()
    try:
        count = db.query(Notification).filter(
            Notification.username == "testuser", Notification.type == "group_added"
        ).count()
        assert count == 0
    finally:
        db.close()
