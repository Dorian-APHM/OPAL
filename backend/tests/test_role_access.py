"""
Tests for role-based access control (C-AUTH-06).

Verifies that endpoints enforce role checks at the code level
(defense-in-depth), independent of the middleware route filtering.

Uses X-Test-Roles header (supported by conftest._FakeAuthMiddleware)
to simulate different user roles.
"""
import pytest

ADMIN = {"X-Test-Roles": "admin"}
CHERCHEUR = {"X-Test-Roles": "chercheur"}
DATA_MANAGER = {"X-Test-Roles": "data-manager"}
MEDECIN = {"X-Test-Roles": "medecin"}


# ── Admin endpoints (require admin role) ──

class TestAdminEndpoints:

    def test_audit_logs_forbidden_for_chercheur(self, client):
        assert client.get("/api/audit/logs", headers=CHERCHEUR).status_code == 403

    def test_audit_export_forbidden_for_chercheur(self, client):
        assert client.get("/api/audit/export", headers=CHERCHEUR).status_code == 403

    def test_audit_stats_forbidden_for_chercheur(self, client):
        assert client.get("/api/audit/stats", headers=CHERCHEUR).status_code == 403

    def test_audit_dates_forbidden_for_chercheur(self, client):
        assert client.get("/api/audit/dates", headers=CHERCHEUR).status_code == 403

    def test_admin_users_forbidden_for_chercheur(self, client):
        assert client.get("/api/admin/users", headers=CHERCHEUR).status_code == 403

    def test_admin_add_user_forbidden_for_chercheur(self, client):
        resp = client.post("/api/admin/users/add", headers=CHERCHEUR, json={
            "username": "hacker", "role": "admin",
        })
        assert resp.status_code == 403

    def test_admin_access_requests_forbidden_for_chercheur(self, client):
        assert client.get("/api/admin/access-requests", headers=CHERCHEUR).status_code == 403

    def test_audit_logs_allowed_for_admin(self, client):
        resp = client.get("/api/audit/logs", headers=ADMIN)
        assert resp.status_code != 403

    def test_admin_forbidden_for_data_manager(self, client):
        assert client.get("/api/admin/users", headers=DATA_MANAGER).status_code == 403

    def test_admin_forbidden_for_medecin(self, client):
        assert client.get("/api/admin/users", headers=MEDECIN).status_code == 403


# ── Groups endpoints (require admin or data-manager for writes) ──

class TestGroupsRoleCheck:

    def test_list_groups_allowed_for_chercheur(self, client):
        assert client.get("/api/groups/", headers=CHERCHEUR).status_code == 200

    def test_create_group_forbidden_for_chercheur(self, client):
        resp = client.post("/api/groups/", headers=CHERCHEUR, json={
            "name": "hacker_group", "description": "test",
        })
        assert resp.status_code == 403

    def test_create_group_forbidden_for_medecin(self, client):
        resp = client.post("/api/groups/", headers=MEDECIN, json={
            "name": "med_group",
        })
        assert resp.status_code == 403

    def test_delete_group_forbidden_for_chercheur(self, client):
        client.post("/api/groups/", headers=ADMIN, json={"name": "protected_grp"})
        assert client.delete("/api/groups/protected_grp", headers=CHERCHEUR).status_code == 403

    def test_update_group_forbidden_for_chercheur(self, client):
        client.post("/api/groups/", headers=ADMIN, json={"name": "upd_grp"})
        resp = client.put("/api/groups/upd_grp", headers=CHERCHEUR, json={"description": "hacked"})
        assert resp.status_code == 403

    def test_add_member_forbidden_for_chercheur(self, client):
        client.post("/api/groups/", headers=ADMIN, json={"name": "mem_grp"})
        resp = client.post("/api/groups/mem_grp/members", headers=CHERCHEUR, json={"username": "hacker"})
        assert resp.status_code == 403

    def test_remove_member_forbidden_for_chercheur(self, client):
        client.post("/api/groups/", headers=ADMIN, json={"name": "rm_grp", "members": ["alice"]})
        resp = client.delete("/api/groups/rm_grp/members/alice", headers=CHERCHEUR)
        assert resp.status_code == 403

    def test_create_group_allowed_for_admin(self, client):
        resp = client.post("/api/groups/", headers=ADMIN, json={"name": "admin_grp"})
        assert resp.status_code == 200

    def test_create_group_allowed_for_data_manager(self, client):
        resp = client.post("/api/groups/", headers=DATA_MANAGER, json={"name": "dm_grp"})
        assert resp.status_code == 200


# ── CDM Access endpoints (require can_manage_access / can_clear_all_grants) ──

class TestCdmAccessRoleCheck:

    def _create_cdm(self, client):
        client.post("/api/cdm/", headers=ADMIN, json={
            "name": "cdm_rbac", "db_host": "db.example.com", "db_port": 5432,
            "db_name": "db", "db_user": "u", "db_password": "p",
        })

    def test_grant_forbidden_for_chercheur(self, client):
        self._create_cdm(client)
        resp = client.post("/api/cdm-access/grant", headers=CHERCHEUR, json={
            "cdm_name": "cdm_rbac", "username": "hacker",
        })
        assert resp.status_code == 403

    def test_revoke_forbidden_for_chercheur(self, client):
        resp = client.post("/api/cdm-access/revoke", headers=CHERCHEUR, json={
            "cdm_name": "any_cdm", "username": "anyone",
        })
        assert resp.status_code == 403

    def test_list_access_forbidden_for_chercheur(self, client):
        assert client.get("/api/cdm-access/", headers=CHERCHEUR).status_code == 403

    def test_cdms_for_user_allowed_for_chercheur(self, client):
        resp = client.get("/api/cdm-access/cdms-for-user", headers=CHERCHEUR)
        assert resp.status_code == 200

    def test_clear_all_forbidden_for_chercheur(self, client):
        assert client.delete("/api/cdm-access/cdm/any", headers=CHERCHEUR).status_code == 403

    def test_clear_all_forbidden_for_data_manager(self, client):
        """data-manager has can_manage_access but NOT can_clear_all_grants."""
        assert client.delete("/api/cdm-access/cdm/any", headers=DATA_MANAGER).status_code == 403

    def test_grant_allowed_for_admin(self, client):
        self._create_cdm(client)
        resp = client.post("/api/cdm-access/grant", headers=ADMIN, json={
            "cdm_name": "cdm_rbac", "username": "researcher",
        })
        assert resp.status_code == 200

    def test_grant_allowed_for_data_manager(self, client):
        self._create_cdm(client)
        resp = client.post("/api/cdm-access/grant", headers=DATA_MANAGER, json={
            "cdm_name": "cdm_rbac", "username": "researcher",
        })
        assert resp.status_code == 200
