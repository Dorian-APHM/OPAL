"""
Tests for role-based access control (C-AUTH-06).

Verifies that endpoints enforce role checks at the code level
(defense-in-depth), independent of the middleware route filtering.

Uses X-Test-Roles header (supported by conftest._FakeAuthMiddleware)
to simulate different user roles.
"""
import pytest
from unittest.mock import patch

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

    def test_audit_logs_allowed_for_admin(self, client, tmp_path):
        with patch("audit.logger.AUDIT_LOG_DIR", tmp_path):
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


# ── IDOR tests — verify ownership enforcement ──

USER_A = {"X-Test-Username": "alice", "X-Test-Roles": "chercheur"}
USER_B = {"X-Test-Username": "bob", "X-Test-Roles": "chercheur"}


class TestIDORSavedQueries:

    def test_user_b_cannot_update_user_a_query(self, client):
        resp = client.post("/api/saved-queries/", headers=USER_A, json={
            "cdm_name": "test", "name": "alice_query", "sql": "SELECT 1",
        })
        query_id = resp.json()["id"]

        resp = client.put(f"/api/saved-queries/{query_id}", headers=USER_B, json={
            "name": "hacked",
        })
        assert resp.status_code == 403

    def test_user_b_cannot_delete_user_a_query(self, client):
        resp = client.post("/api/saved-queries/", headers=USER_A, json={
            "cdm_name": "test", "name": "alice_query2", "sql": "SELECT 1",
        })
        query_id = resp.json()["id"]
        resp = client.delete(f"/api/saved-queries/{query_id}", headers=USER_B)
        assert resp.status_code == 403

    def test_owner_can_update_own_query(self, client):
        resp = client.post("/api/saved-queries/", headers=USER_A, json={
            "cdm_name": "test", "name": "my_query", "sql": "SELECT 1",
        })
        query_id = resp.json()["id"]
        resp = client.put(f"/api/saved-queries/{query_id}", headers=USER_A, json={
            "name": "updated",
        })
        assert resp.status_code == 200


class TestIDORCohortDelete:

    def _create_cdm_and_cohort(self, client, cohort_name, headers):
        """Create a CDM then a cohort owned by the given user."""
        # Ensure CDM exists (idempotent via 409)
        client.post("/api/cdm/", headers=ADMIN, json={
            "name": "idor_cdm", "db_host": "db.example.com", "db_port": 5432,
            "db_name": "db", "db_user": "u", "db_password": "p",
        })
        resp = client.post("/api/cohorts/", headers=headers, json={
            "name": cohort_name, "cdm_name": "idor_cdm", "criteria": {"type": "ALL"},
        })
        assert resp.status_code == 200, resp.text
        return resp.json()["id"]

    def test_user_b_cannot_delete_user_a_cohort(self, client):
        cohort_id = self._create_cdm_and_cohort(client, "alice_c1", USER_A)
        resp = client.delete(f"/api/cohorts/{cohort_id}", headers=USER_B)
        assert resp.status_code == 403

    def test_owner_can_delete_own_cohort(self, client):
        cohort_id = self._create_cdm_and_cohort(client, "alice_c2", USER_A)
        resp = client.delete(f"/api/cohorts/{cohort_id}", headers=USER_A)
        assert resp.status_code == 200

    def test_admin_can_delete_any_cohort(self, client):
        cohort_id = self._create_cdm_and_cohort(client, "alice_c3", USER_A)
        resp = client.delete(f"/api/cohorts/{cohort_id}", headers=ADMIN)
        assert resp.status_code == 200


class TestIDORNotifications:

    def test_user_b_cannot_read_user_a_notification(self, client):
        # Create notification for alice (admin-only endpoint)
        resp = client.post("/api/notifications/create", headers=ADMIN, json={
            "username": "alice", "type": "info", "title": "Test", "message": "for alice",
        })
        assert resp.status_code == 200, resp.text
        notif_id = resp.json()["id"]

        # Bob tries to mark it as read
        resp = client.post(f"/api/notifications/{notif_id}/read", headers=USER_B)
        assert resp.status_code == 404  # filtered by username, not found


class TestIDORConceptSets:

    def test_user_b_cannot_update_user_a_concept_set(self, client):
        resp = client.post("/api/concept-sets/", headers=USER_A, json={
            "name": "alice_cs", "cdm_name": "test", "domain": "Condition", "concepts": [],
        })
        cs_id = resp.json()["id"]
        resp = client.put(f"/api/concept-sets/{cs_id}", headers=USER_B, json={
            "name": "hacked",
        })
        assert resp.status_code == 403

    def test_user_b_cannot_delete_user_a_concept_set(self, client):
        resp = client.post("/api/concept-sets/", headers=USER_A, json={
            "name": "alice_cs2", "cdm_name": "test", "domain": "Drug", "concepts": [],
        })
        cs_id = resp.json()["id"]
        resp = client.delete(f"/api/concept-sets/{cs_id}", headers=USER_B)
        assert resp.status_code == 403


class TestIDORCohortTemplates:

    def test_user_b_cannot_delete_user_a_template(self, client):
        resp = client.post("/api/cohort-templates/", headers=USER_A, json={
            "name": "alice_tpl", "description": "test", "criteria_json": {},
        })
        tpl_id = resp.json()["id"]
        resp = client.delete(f"/api/cohort-templates/{tpl_id}", headers=USER_B)
        assert resp.status_code == 403
