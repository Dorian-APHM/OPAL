"""
Tests for admin user management endpoints (Keycloak proxy).
All Keycloak HTTP calls are mocked.
"""
import pytest


class MockResponse:
    """Configurable mock for requests.Response."""
    def __init__(self, json_data=None, status_code=200, headers=None):
        self._json = json_data or {}
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    @property
    def ok(self):
        return self.status_code < 400


# ──── GET /api/admin/users ────


def test_list_users_keycloak_unavailable(client, monkeypatch):
    import modules.admin_router as admin_mod
    monkeypatch.setattr(admin_mod, "_get_keycloak_admin_token", lambda: None)

    resp = client.get("/api/admin/users")
    assert resp.status_code == 200
    data = resp.json()
    assert data["users"] == []
    assert data["error"] == "Keycloak admin unavailable"


def test_list_users_success(client, monkeypatch):
    import modules.admin_router as admin_mod
    import requests as http_requests

    monkeypatch.setattr(admin_mod, "_get_keycloak_admin_token", lambda: "fake-token")

    alice = {
        "id": "uid-1",
        "username": "alice",
        "email": "alice@example.com",
        "firstName": "Alice",
        "lastName": "Smith",
        "enabled": True,
        "createdTimestamp": 1700000000000,
    }
    bob = {
        "id": "uid-2",
        "username": "bob",
        "email": "bob@example.com",
        "firstName": "Bob",
        "lastName": "Jones",
        "enabled": False,
        "createdTimestamp": 1700000001000,
    }

    # The endpoint iterates over roles and fetches users per role
    def mock_get(url, **kwargs):
        if "/roles/admin/users" in url:
            return MockResponse(json_data=[alice])
        if "/roles/chercheur/users" in url:
            return MockResponse(json_data=[bob])
        if "/roles/data-manager/users" in url:
            return MockResponse(json_data=[])
        if "/roles/medecin/users" in url:
            return MockResponse(json_data=[])
        return MockResponse(json_data=[])

    monkeypatch.setattr(http_requests, "get", mock_get)

    resp = client.get("/api/admin/users")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["users"]) == 2
    # Sort by username for deterministic assertion
    users_sorted = sorted(data["users"], key=lambda u: u["username"])
    assert users_sorted[0]["username"] == "alice"
    assert users_sorted[0]["roles"] == ["admin"]
    assert users_sorted[0]["enabled"] is True
    assert users_sorted[1]["username"] == "bob"
    assert users_sorted[1]["roles"] == ["chercheur"]


def test_list_users_keycloak_error(client, monkeypatch):
    import modules.admin_router as admin_mod
    import requests as http_requests

    monkeypatch.setattr(admin_mod, "_get_keycloak_admin_token", lambda: "fake-token")

    def mock_get(url, **kwargs):
        raise Exception("Connection refused")

    monkeypatch.setattr(http_requests, "get", mock_get)

    resp = client.get("/api/admin/users")
    data = resp.json()
    assert data["users"] == []
    assert "error" in data


# ──── POST /api/admin/users/{id}/roles ────


def test_assign_role_missing_body(client, monkeypatch):
    import modules.admin_router as admin_mod
    monkeypatch.setattr(admin_mod, "_get_keycloak_admin_token", lambda: "fake-token")

    resp = client.post("/api/admin/users/uid-1/roles", json={})
    assert resp.status_code == 422  # Pydantic validation: 'role' is required


def test_assign_role_keycloak_unavailable(client, monkeypatch):
    import modules.admin_router as admin_mod
    monkeypatch.setattr(admin_mod, "_get_keycloak_admin_token", lambda: None)

    resp = client.post("/api/admin/users/uid-1/roles", json={"role": "chercheur"})
    assert resp.status_code == 503


def test_assign_role_success(client, monkeypatch):
    import modules.admin_router as admin_mod
    import requests as http_requests

    monkeypatch.setattr(admin_mod, "_get_keycloak_admin_token", lambda: "fake-token")

    def mock_get(url, **kwargs):
        return MockResponse(json_data={"id": "role-id", "name": "chercheur"})

    def mock_post(url, **kwargs):
        return MockResponse()

    monkeypatch.setattr(http_requests, "get", mock_get)
    monkeypatch.setattr(http_requests, "post", mock_post)

    resp = client.post("/api/admin/users/uid-1/roles", json={"role": "chercheur"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["role"] == "chercheur"
    assert data["action"] == "assigned"


def test_assign_role_not_found(client, monkeypatch):
    import modules.admin_router as admin_mod
    import requests as http_requests

    monkeypatch.setattr(admin_mod, "_get_keycloak_admin_token", lambda: "fake-token")

    def mock_get(url, **kwargs):
        return MockResponse(status_code=404)

    monkeypatch.setattr(http_requests, "get", mock_get)

    resp = client.post("/api/admin/users/uid-1/roles", json={"role": "nonexistent"})
    assert resp.status_code == 404


# ──── DELETE /api/admin/users/{id}/roles/{role} ────


def test_remove_role_keycloak_unavailable(client, monkeypatch):
    import modules.admin_router as admin_mod
    monkeypatch.setattr(admin_mod, "_get_keycloak_admin_token", lambda: None)

    resp = client.delete("/api/admin/users/uid-1/roles/chercheur")
    assert resp.status_code == 503


def test_remove_role_success(client, monkeypatch):
    import modules.admin_router as admin_mod
    import requests as http_requests

    monkeypatch.setattr(admin_mod, "_get_keycloak_admin_token", lambda: "fake-token")

    def mock_get(url, **kwargs):
        return MockResponse(json_data={"id": "role-id", "name": "chercheur"})

    def mock_delete(url, **kwargs):
        return MockResponse()

    monkeypatch.setattr(http_requests, "get", mock_get)
    monkeypatch.setattr(http_requests, "delete", mock_delete)

    resp = client.delete("/api/admin/users/uid-1/roles/chercheur")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["role"] == "chercheur"
    assert data["action"] == "removed"


def test_remove_role_not_found(client, monkeypatch):
    import modules.admin_router as admin_mod
    import requests as http_requests

    monkeypatch.setattr(admin_mod, "_get_keycloak_admin_token", lambda: "fake-token")

    def mock_get(url, **kwargs):
        return MockResponse(status_code=404)

    monkeypatch.setattr(http_requests, "get", mock_get)

    resp = client.delete("/api/admin/users/uid-1/roles/nonexistent")
    assert resp.status_code == 404


# ──── PUT /api/admin/users/{id}/toggle ────


def test_toggle_user_keycloak_unavailable(client, monkeypatch):
    import modules.admin_router as admin_mod
    monkeypatch.setattr(admin_mod, "_get_keycloak_admin_token", lambda: None)

    resp = client.put("/api/admin/users/uid-1/toggle", json={"enabled": False})
    assert resp.status_code == 503


def test_toggle_user_enable(client, monkeypatch):
    import modules.admin_router as admin_mod
    import requests as http_requests

    monkeypatch.setattr(admin_mod, "_get_keycloak_admin_token", lambda: "fake-token")

    def mock_put(url, **kwargs):
        return MockResponse()

    monkeypatch.setattr(http_requests, "put", mock_put)

    resp = client.put("/api/admin/users/uid-1/toggle", json={"enabled": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["enabled"] is True


def test_toggle_user_disable(client, monkeypatch):
    import modules.admin_router as admin_mod
    import requests as http_requests

    monkeypatch.setattr(admin_mod, "_get_keycloak_admin_token", lambda: "fake-token")

    def mock_put(url, **kwargs):
        return MockResponse()

    monkeypatch.setattr(http_requests, "put", mock_put)

    resp = client.put("/api/admin/users/uid-1/toggle", json={"enabled": False})
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False


def test_toggle_user_keycloak_error(client, monkeypatch):
    import modules.admin_router as admin_mod
    import requests as http_requests

    monkeypatch.setattr(admin_mod, "_get_keycloak_admin_token", lambda: "fake-token")

    def mock_put(url, **kwargs):
        return MockResponse(status_code=500)

    monkeypatch.setattr(http_requests, "put", mock_put)

    resp = client.put("/api/admin/users/uid-1/toggle", json={"enabled": True})
    assert resp.status_code == 500
