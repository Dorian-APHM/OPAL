"""
Access-control regression tests (IDOR / broken access control).

Covers the fixes for:
- per-cohort access on the cohort-id endpoints (execute/export/characterization/
  pathways-result/compare), which previously let any user act on another user's
  cohorts by id;
- concept-set listing no longer leaking every CDM's sets when cdm_name is omitted;
- check_cdm_access being actually enforced on lineage endpoints.
"""
import pytest

from db.models import Cohort, CohortVersion, ConceptSet, LineageDoc


def _db():
    from tests.conftest import TestSession
    return TestSession()


def _make_cohort(owner="alice", cdm="cdm_a", name="C"):
    db = _db()
    try:
        c = Cohort(cdm_name=cdm, name=name, created_by=owner)
        db.add(c)
        db.flush()
        db.add(CohortVersion(cohort_id=c.id, version=1, criteria_json={}, generated_sql="SELECT 1"))
        db.commit()
        db.refresh(c)
        return c.id
    finally:
        db.close()


# Non-admin headers for two distinct users.
ALICE = {"X-Test-Username": "alice", "X-Test-Roles": "chercheur"}
BOB = {"X-Test-Username": "bob", "X-Test-Roles": "chercheur"}


# ── Per-cohort access on id-based endpoints ──

@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/cohorts/{id}/characterization"),
        ("get", "/api/cohorts/{id}/pathways-result"),
        ("post", "/api/cohorts/{id}/execute"),
        ("get", "/api/cohorts/{id}/export"),
    ],
)
def test_cohort_id_endpoints_deny_non_owner(client, method, path):
    cid = _make_cohort(owner="alice")
    url = path.format(id=cid)
    resp = getattr(client, method)(url, headers=BOB)
    assert resp.status_code == 403, f"{method} {url} should be forbidden for non-owner"


def test_compare_denies_when_a_cohort_is_not_accessible(client):
    a = _make_cohort(owner="alice", name="A")
    b = _make_cohort(owner="alice", name="B")
    resp = client.post(
        "/api/cohorts/compare",
        json={"cdm_name": "cdm_a", "cohort_id_a": a, "cohort_id_b": b},
        headers=BOB,
    )
    assert resp.status_code == 403


def test_owner_passes_access_check(client):
    """The owner must still reach their own cohort (no regression)."""
    cid = _make_cohort(owner="alice")
    resp = client.get(f"/api/cohorts/{cid}/characterization", headers=ALICE)
    assert resp.status_code == 200


# ── Concept-set listing scope ──

def test_concept_set_list_without_cdm_returns_empty(client):
    db = _db()
    try:
        db.add(ConceptSet(cdm_name="cdm_a", name="S1", domain="Drug", concepts_json="{}", created_by="alice"))
        db.add(ConceptSet(cdm_name="cdm_b", name="S2", domain="Drug", concepts_json="{}", created_by="bob"))
        db.commit()
    finally:
        db.close()
    # No cdm_name → must not leak every CDM's concept sets.
    resp = client.get("/api/concept-sets/", headers=BOB)
    assert resp.status_code == 200
    assert resp.json()["concept_sets"] == []
    # Scoped to one CDM → only that CDM's sets.
    resp = client.get("/api/concept-sets/", params={"cdm_name": "cdm_a"}, headers=BOB)
    names = [s["name"] for s in resp.json()["concept_sets"]]
    assert names == ["S1"]


# ── check_cdm_access enforced on lineage ──

def test_lineage_enforces_cdm_access(client, monkeypatch):
    import config
    import auth.keycloak as kc
    import utils.cdm_helper as helper

    db = _db()
    try:
        db.add(LineageDoc(cdm_name="cdm_secret", filename="x.html", lineage_json={}, uploaded_by="alice"))
        db.commit()
    finally:
        db.close()

    # Turn auth on for this test and deny the CDM.
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(helper, "AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(kc, "_check_cdm_access", lambda cdm, user: False)

    resp = client.get("/api/lineage/cdm_secret", headers=BOB)
    assert resp.status_code == 403
