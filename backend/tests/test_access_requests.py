"""
Tests for access request endpoints (sign-up workflow).
"""
import pytest


def _make_request_body(**overrides):
    base = {
        "username": "jdupont",
        "email": "jean.dupont@hopital.fr",
        "first_name": "Jean",
        "last_name": "Dupont",
        "requested_role": "chercheur",
    }
    base.update(overrides)
    return base


# ──── POST /api/access-requests ────


def test_submit_access_request(client):
    body = _make_request_body()
    resp = client.post("/api/access-requests", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "id" in data


def test_submit_duplicate_username(client):
    body = _make_request_body()
    client.post("/api/access-requests", json=body)
    resp = client.post("/api/access-requests", json=body)
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


def test_submit_missing_required_field(client):
    for field in ["username", "email", "first_name", "last_name", "requested_role"]:
        body = _make_request_body()
        body[field] = ""
        resp = client.post("/api/access-requests", json=body)
        assert resp.status_code == 400, f"Field {field} should be required"
        assert field in resp.json()["detail"]


def test_submit_missing_field_key(client):
    body = _make_request_body()
    del body["email"]
    resp = client.post("/api/access-requests", json=body)
    assert resp.status_code == 400


def test_submit_invalid_role(client):
    body = _make_request_body(requested_role="superadmin")
    resp = client.post("/api/access-requests", json=body)
    assert resp.status_code == 400
    assert "Invalid role" in resp.json()["detail"]


def test_submit_valid_roles(client):
    for i, role in enumerate(["admin", "data-manager", "chercheur", "medecin"]):
        body = _make_request_body(username=f"user_{i}", requested_role=role)
        resp = client.post("/api/access-requests", json=body)
        assert resp.status_code == 200, f"Role {role} should be accepted"


def test_submit_strips_whitespace(client):
    body = _make_request_body(username="  jdupont  ", email="  a@b.com  ")
    resp = client.post("/api/access-requests", json=body)
    assert resp.status_code == 200

    # Verify stored values are stripped
    list_resp = client.get("/api/admin/access-requests?status_filter=all")
    reqs = list_resp.json()["requests"]
    assert reqs[0]["username"] == "jdupont"
    assert reqs[0]["email"] == "a@b.com"


# ──── GET /api/admin/access-requests ────


def test_list_access_requests_empty(client):
    resp = client.get("/api/admin/access-requests")
    assert resp.status_code == 200
    assert resp.json()["requests"] == []


def test_list_access_requests_pending(client):
    client.post("/api/access-requests", json=_make_request_body(username="u1"))
    client.post("/api/access-requests", json=_make_request_body(username="u2"))
    resp = client.get("/api/admin/access-requests")
    assert len(resp.json()["requests"]) == 2


def test_list_access_requests_filter_status(client):
    client.post("/api/access-requests", json=_make_request_body(username="u1"))
    # Reject u1
    reqs = client.get("/api/admin/access-requests").json()["requests"]
    client.post(f"/api/admin/access-requests/{reqs[0]['id']}/reject")

    # Submit another
    client.post("/api/access-requests", json=_make_request_body(username="u2"))

    # Filter: pending only
    pending = client.get("/api/admin/access-requests?status_filter=pending").json()["requests"]
    assert len(pending) == 1
    assert pending[0]["username"] == "u2"

    # Filter: all
    all_reqs = client.get("/api/admin/access-requests?status_filter=all").json()["requests"]
    assert len(all_reqs) == 2


def test_list_access_requests_returns_full_fields(client):
    client.post("/api/access-requests", json=_make_request_body())
    reqs = client.get("/api/admin/access-requests").json()["requests"]
    r = reqs[0]
    assert r["username"] == "jdupont"
    assert r["email"] == "jean.dupont@hopital.fr"
    assert r["first_name"] == "Jean"
    assert r["last_name"] == "Dupont"
    assert r["requested_role"] == "chercheur"
    assert r["status"] == "pending"
    assert r["reviewed_by"] is None
    assert r["reviewed_at"] is None
    assert r["created_at"] is not None


# ──── POST /api/admin/access-requests/{id}/reject ────


def test_reject_access_request(client):
    client.post("/api/access-requests", json=_make_request_body())
    reqs = client.get("/api/admin/access-requests").json()["requests"]
    req_id = reqs[0]["id"]

    resp = client.post(f"/api/admin/access-requests/{req_id}/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Verify status changed
    all_reqs = client.get("/api/admin/access-requests?status_filter=all").json()["requests"]
    rejected = [r for r in all_reqs if r["id"] == req_id][0]
    assert rejected["status"] == "rejected"
    assert rejected["reviewed_by"] == "testuser"
    assert rejected["reviewed_at"] is not None


def test_reject_nonexistent_request(client):
    resp = client.post("/api/admin/access-requests/999/reject")
    assert resp.status_code == 404


def test_reject_already_rejected(client):
    client.post("/api/access-requests", json=_make_request_body())
    reqs = client.get("/api/admin/access-requests").json()["requests"]
    req_id = reqs[0]["id"]

    client.post(f"/api/admin/access-requests/{req_id}/reject")
    resp = client.post(f"/api/admin/access-requests/{req_id}/reject")
    assert resp.status_code == 400
    assert "already" in resp.json()["detail"]


# ──── POST /api/admin/access-requests/{id}/approve ────


def test_approve_nonexistent_request(client):
    resp = client.post("/api/admin/access-requests/999/approve")
    assert resp.status_code == 404


def test_approve_already_rejected(client):
    client.post("/api/access-requests", json=_make_request_body())
    reqs = client.get("/api/admin/access-requests").json()["requests"]
    req_id = reqs[0]["id"]

    client.post(f"/api/admin/access-requests/{req_id}/reject")
    resp = client.post(f"/api/admin/access-requests/{req_id}/approve")
    assert resp.status_code == 400
    assert "already" in resp.json()["detail"]


def test_approve_request_keycloak_unavailable(client, monkeypatch):
    """When Keycloak is unavailable, approve should return 503."""
    client.post("/api/access-requests", json=_make_request_body())
    reqs = client.get("/api/admin/access-requests").json()["requests"]
    req_id = reqs[0]["id"]

    # Mock _get_keycloak_admin_token to return None
    import main
    monkeypatch.setattr(main, "_get_keycloak_admin_token", lambda: None)

    resp = client.post(f"/api/admin/access-requests/{req_id}/approve")
    assert resp.status_code == 503


def test_approve_request_success(client, monkeypatch):
    """Full approve flow with mocked Keycloak."""
    import main

    client.post("/api/access-requests", json=_make_request_body())
    reqs = client.get("/api/admin/access-requests").json()["requests"]
    req_id = reqs[0]["id"]

    # Mock Keycloak admin token
    monkeypatch.setattr(main, "_get_keycloak_admin_token", lambda: "fake-token")

    # Mock requests.post for user creation
    class FakeResponse:
        status_code = 201
        headers = {"Location": "http://keycloak/users/fake-uid-123"}
        def raise_for_status(self): pass
        def json(self): return {"id": "role-id", "name": "chercheur"}
        @property
        def ok(self): return True

    import requests as http_requests
    original_post = http_requests.post
    original_get = http_requests.get

    def mock_post(url, **kwargs):
        return FakeResponse()

    def mock_get(url, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(http_requests, "post", mock_post)
    monkeypatch.setattr(http_requests, "get", mock_get)

    resp = client.post(f"/api/admin/access-requests/{req_id}/approve")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["username"] == "jdupont"
    assert data["temporary_password"] == "jdupont"
    assert data["keycloak_user_id"] == "fake-uid-123"

    # Verify status updated in DB
    all_reqs = client.get("/api/admin/access-requests?status_filter=all").json()["requests"]
    approved = [r for r in all_reqs if r["id"] == req_id][0]
    assert approved["status"] == "approved"
    assert approved["reviewed_by"] == "testuser"
