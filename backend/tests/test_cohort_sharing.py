"""Tests for cohort ownership, sharing, and access control."""
import pytest
from db.models import Cohort, CohortVersion, CohortShare, UserGroup, UserGroupMember, Notification


def _create_cohort(db, cdm_name="test_cdm", name="My Cohort", created_by="testuser"):
    """Insert a cohort directly into DB."""
    cohort = Cohort(cdm_name=cdm_name, name=name, created_by=created_by)
    db.add(cohort)
    db.flush()
    db.add(CohortVersion(cohort_id=cohort.id, version=1, criteria_json={}, generated_sql="SELECT 1"))
    db.commit()
    db.refresh(cohort)
    return cohort


def _get_db():
    from tests.conftest import TestSession
    return TestSession()


# ── Ownership ──

def test_created_by_stored(client):
    """created_by field is stored and returned."""
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="testuser", name="Owned")
        cid = c.id
    finally:
        db.close()

    resp = client.get(f"/api/cohorts/{cid}")
    assert resp.status_code == 200
    assert resp.json()["created_by"] == "testuser"


# ── List returns ownership/sharing metadata ──

def test_list_returns_created_by_and_shared_flag(client):
    """List endpoint includes created_by and shared_with_all."""
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="testuser", name="With Meta")
        c.shared_with_all = 1
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/cohorts/")
    cohort = next(c for c in resp.json()["cohorts"] if c["name"] == "With Meta")
    assert cohort["created_by"] == "testuser"
    assert cohort["shared_with_all"] is True


def test_admin_sees_all_cohorts(client):
    """Admin (testuser from conftest) sees all cohorts."""
    db = _get_db()
    try:
        _create_cohort(db, created_by="testuser", name="Mine")
        _create_cohort(db, created_by="otheruser", name="Others")
    finally:
        db.close()

    resp = client.get("/api/cohorts/")
    names = [c["name"] for c in resp.json()["cohorts"]]
    assert "Mine" in names
    assert "Others" in names


def test_list_includes_public(client):
    """Public cohorts appear in list."""
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="otheruser", name="Public One")
        c.shared_with_all = 1
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/cohorts/")
    names = [c["name"] for c in resp.json()["cohorts"]]
    assert "Public One" in names


def test_list_includes_shared_direct(client):
    """Cohorts shared directly with user appear in list."""
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="otheruser", name="Shared Direct")
        db.add(CohortShare(
            cohort_id=c.id, share_type="user", share_target="testuser", shared_by="otheruser"
        ))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/cohorts/")
    names = [c["name"] for c in resp.json()["cohorts"]]
    assert "Shared Direct" in names


def test_list_includes_shared_via_group(client):
    """Cohorts shared via group appear in list."""
    db = _get_db()
    try:
        db.add(UserGroup(name="team_x", created_by="admin"))
        db.add(UserGroupMember(group_name="team_x", username="testuser", added_by="admin"))
        c = _create_cohort(db, created_by="otheruser", name="Group Shared")
        db.add(CohortShare(
            cohort_id=c.id, share_type="group", share_target="team_x", shared_by="otheruser"
        ))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/cohorts/")
    names = [c["name"] for c in resp.json()["cohorts"]]
    assert "Group Shared" in names


# ── Sharing endpoints ──

def test_share_with_user(client):
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="testuser")
        cid = c.id
    finally:
        db.close()

    resp = client.post(f"/api/cohorts/{cid}/share", json={"share_type": "user", "share_target": "bob"})
    assert resp.status_code == 200
    assert resp.json()["shared_with"]["target"] == "bob"


def test_share_with_group(client):
    db = _get_db()
    try:
        db.add(UserGroup(name="researchers", created_by="admin"))
        db.commit()
        c = _create_cohort(db, created_by="testuser")
        cid = c.id
    finally:
        db.close()

    resp = client.post(f"/api/cohorts/{cid}/share", json={"share_type": "group", "share_target": "researchers"})
    assert resp.status_code == 200
    assert resp.json()["shared_with"]["target"] == "researchers"


def test_share_nonexistent_group_fails(client):
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="testuser")
        cid = c.id
    finally:
        db.close()

    resp = client.post(f"/api/cohorts/{cid}/share", json={"share_type": "group", "share_target": "ghost"})
    assert resp.status_code == 404


def test_share_with_all(client):
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="testuser")
        cid = c.id
    finally:
        db.close()

    resp = client.post(f"/api/cohorts/{cid}/share", json={"share_type": "all"})
    assert resp.status_code == 200
    assert resp.json()["shared_with_all"] is True


def test_share_duplicate_idempotent(client):
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="testuser")
        cid = c.id
    finally:
        db.close()

    client.post(f"/api/cohorts/{cid}/share", json={"share_type": "user", "share_target": "bob"})
    resp = client.post(f"/api/cohorts/{cid}/share", json={"share_type": "user", "share_target": "bob"})
    assert resp.json()["already_shared"] is True


def test_unshare_user(client):
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="testuser")
        cid = c.id
    finally:
        db.close()

    client.post(f"/api/cohorts/{cid}/share", json={"share_type": "user", "share_target": "bob"})
    resp = client.post(f"/api/cohorts/{cid}/unshare", json={"share_type": "user", "share_target": "bob"})
    assert resp.json()["removed"] == 1


def test_unshare_all(client):
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="testuser")
        cid = c.id
    finally:
        db.close()

    client.post(f"/api/cohorts/{cid}/share", json={"share_type": "all"})
    resp = client.post(f"/api/cohorts/{cid}/unshare", json={"share_type": "all"})
    assert resp.json()["shared_with_all"] is False


def test_list_shares(client):
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="testuser")
        cid = c.id
    finally:
        db.close()

    client.post(f"/api/cohorts/{cid}/share", json={"share_type": "user", "share_target": "alice"})
    client.post(f"/api/cohorts/{cid}/share", json={"share_type": "user", "share_target": "bob"})

    resp = client.get(f"/api/cohorts/{cid}/shares")
    assert len(resp.json()["shares"]) == 2


# ── Get cohort detail includes shares ──

def test_get_cohort_includes_shares(client):
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="testuser")
        cid = c.id
    finally:
        db.close()

    client.post(f"/api/cohorts/{cid}/share", json={"share_type": "user", "share_target": "alice"})

    resp = client.get(f"/api/cohorts/{cid}")
    data = resp.json()
    assert "shares" in data
    assert len(data["shares"]) == 1
    assert data["shares"][0]["target"] == "alice"


# ── Delete ──

def test_owner_can_delete(client):
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="testuser")
        cid = c.id
    finally:
        db.close()

    resp = client.delete(f"/api/cohorts/{cid}")
    assert resp.json()["deleted"] is True


def test_delete_cleans_shares(client):
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="testuser")
        cid = c.id
        db.add(CohortShare(cohort_id=cid, share_type="user", share_target="bob", shared_by="testuser"))
        db.commit()
    finally:
        db.close()

    client.delete(f"/api/cohorts/{cid}")

    db2 = _get_db()
    try:
        assert db2.query(CohortShare).filter(CohortShare.cohort_id == cid).count() == 0
    finally:
        db2.close()


# ── Admin by-user view ──

def test_admin_by_user(client):
    db = _get_db()
    try:
        _create_cohort(db, created_by="alice", name="Alice C")
        _create_cohort(db, created_by="bob", name="Bob C")
    finally:
        db.close()

    resp = client.get("/api/cohorts/admin/by-user")
    assert resp.status_code == 200
    users = resp.json()["users"]
    assert "alice" in users
    assert "bob" in users
    assert users["alice"]["created"][0]["name"] == "Alice C"


def test_admin_by_user_shows_shares(client):
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="alice", name="Alice's")
        db.add(CohortShare(cohort_id=c.id, share_type="user", share_target="bob", shared_by="alice"))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/cohorts/admin/by-user")
    users = resp.json()["users"]
    assert "bob" in users
    assert len(users["bob"]["shared_with"]) == 1


# ── Notifications on share ──

def test_share_user_creates_notification(client):
    """Sharing a cohort with a user creates a cohort_shared notification."""
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="testuser", name="Notif Cohort")
        cid = c.id
    finally:
        db.close()

    client.post(f"/api/cohorts/{cid}/share", json={"share_type": "user", "share_target": "bob"})

    db2 = _get_db()
    try:
        notifs = db2.query(Notification).filter(
            Notification.username == "bob", Notification.type == "cohort_shared"
        ).all()
        assert len(notifs) == 1
        assert "Notif Cohort" in notifs[0].title
    finally:
        db2.close()


def test_share_group_creates_notifications_for_members(client):
    """Sharing with a group notifies all group members except the sharer."""
    db = _get_db()
    try:
        db.add(UserGroup(name="notif_grp", created_by="admin"))
        db.add(UserGroupMember(group_name="notif_grp", username="alice", added_by="admin"))
        db.add(UserGroupMember(group_name="notif_grp", username="bob", added_by="admin"))
        db.add(UserGroupMember(group_name="notif_grp", username="testuser", added_by="admin"))  # sharer
        db.commit()
        c = _create_cohort(db, created_by="testuser", name="Group Notif")
        cid = c.id
    finally:
        db.close()

    client.post(f"/api/cohorts/{cid}/share", json={"share_type": "group", "share_target": "notif_grp"})

    db2 = _get_db()
    try:
        notifs = db2.query(Notification).filter(Notification.type == "cohort_shared").all()
        notified_users = {n.username for n in notifs}
        assert "alice" in notified_users
        assert "bob" in notified_users
        assert "testuser" not in notified_users  # sharer not notified
    finally:
        db2.close()


def test_share_duplicate_no_extra_notification(client):
    """Sharing again with the same user does not create a duplicate notification."""
    db = _get_db()
    try:
        c = _create_cohort(db, created_by="testuser", name="Dup Notif")
        cid = c.id
    finally:
        db.close()

    client.post(f"/api/cohorts/{cid}/share", json={"share_type": "user", "share_target": "bob"})
    client.post(f"/api/cohorts/{cid}/share", json={"share_type": "user", "share_target": "bob"})

    db2 = _get_db()
    try:
        count = db2.query(Notification).filter(
            Notification.username == "bob", Notification.type == "cohort_shared"
        ).count()
        assert count == 1  # only one notification, not two
    finally:
        db2.close()
