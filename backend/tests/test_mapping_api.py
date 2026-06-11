"""
Tests for the mapping module API endpoints.
Uses the shared conftest.py fixtures for database setup.
Mapping endpoints that require a real OMOP CDM (unmapped, suggest) are tested
via mocking the CDM connection.
"""
import pytest

from db.models import AnalysisSnapshot
from tests.conftest import TestSession


@pytest.fixture
def cdm_name(client):
    """Create a test CDM and return its name."""
    client.post("/api/cdm/", json={
        "name": "test_mapping_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "testdb",
        "db_user": "user",
        "db_password": "pass",
        "omop_schema": "omop_cdm",
    })
    return "test_mapping_cdm"


@pytest.fixture
def cdm_with_snapshots(cdm_name):
    """Create snapshots so the dashboard has data."""
    db = TestSession()
    snapshot = AnalysisSnapshot(
        cdm_name=cdm_name,
        domain="Condition",
        version=1,
        results={
            "mapping": {
                "terms": {
                    "total_terms": 100,
                    "mapped_terms": 70,
                    "unmapped_terms": 30,
                    "pct_terms_mapped": 70.0,
                },
                "rows": {
                    "total_rows": 10000,
                    "mapped_rows": 8000,
                    "unmapped_rows": 2000,
                    "pct_rows_mapped": 80.0,
                },
            }
        },
    )
    db.add(snapshot)
    db.commit()
    db.close()
    return cdm_name


# ──── Dashboard tests ────

def test_dashboard_empty(client, cdm_name):
    resp = client.get(f"/api/mapping/dashboard/{cdm_name}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cdm_name"] == cdm_name
    assert data["domains"] == []
    assert data["decisions_summary"] == {}


def test_dashboard_with_snapshots(client, cdm_with_snapshots):
    resp = client.get(f"/api/mapping/dashboard/{cdm_with_snapshots}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["domains"]) >= 1
    cond = next(d for d in data["domains"] if d["domain"] == "Condition")
    assert cond["total_terms"] == 100
    assert cond["mapped_terms"] == 70
    assert cond["pct_terms_mapped"] == 70.0


def test_dashboard_with_decisions(client, cdm_name):
    # Record a decision
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name,
        "domain": "Condition",
        "source_value": "E11",
        "action": "approved",
        "target_concept_id": 201826,
        "target_concept_name": "Type 2 diabetes",
    })
    resp = client.get(f"/api/mapping/dashboard/{cdm_name}")
    data = resp.json()
    assert data["decisions_summary"].get("approved", 0) == 1


# ──── Evolution tests ────

def test_evolution_empty(client, cdm_name):
    resp = client.get(f"/api/mapping/dashboard/{cdm_name}/evolution", params={"domain": "Condition"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["evolution"] == []


def test_evolution_with_snapshots(client, cdm_with_snapshots):
    resp = client.get(f"/api/mapping/dashboard/{cdm_with_snapshots}/evolution", params={"domain": "Condition"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["evolution"]) == 1
    assert data["evolution"][0]["pct_terms_mapped"] == 70.0


# ──── Decision tests ────

def test_decide_approved(client, cdm_name):
    resp = client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name,
        "domain": "Condition",
        "source_value": "E11",
        "source_name": "Diabetes",
        "action": "approved",
        "target_concept_id": 201826,
        "target_concept_name": "Type 2 diabetes",
        "target_vocabulary_id": "SNOMED",
        "suggestion_source": "exact",
        "confidence_score": 95.0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "approved"
    assert "id" in data


def test_decide_rejected(client, cdm_name):
    resp = client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name,
        "domain": "Drug",
        "source_value": "METFORMIN",
        "action": "rejected",
    })
    assert resp.status_code == 200
    assert resp.json()["action"] == "rejected"


def test_decide_modified(client, cdm_name):
    resp = client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name,
        "domain": "Condition",
        "source_value": "E11.9",
        "action": "modified",
        "target_concept_id": 443238,
        "target_concept_name": "DM Type 2 unspecified",
    })
    assert resp.status_code == 200
    assert resp.json()["action"] == "modified"


def test_decide_invalid_action(client, cdm_name):
    resp = client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name,
        "domain": "Condition",
        "source_value": "E11",
        "action": "invalid_action",
    })
    assert resp.status_code == 422  # Pydantic pattern validation rejects invalid action


def test_decide_bulk(client, cdm_name):
    resp = client.post("/api/mapping/decide/bulk", json={
        "cdm_name": cdm_name,
        "domain": "Condition",
        "action": "approved",
        "source_values": ["E11", "E13", "J45"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "approved"
    assert data["count"] == 3


def test_decide_bulk_skips_existing(client, cdm_name):
    # First, create a decision
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name,
        "domain": "Condition",
        "source_value": "E11",
        "action": "approved",
        "target_concept_id": 201826,
    })
    # Bulk with same source_value should skip it
    resp = client.post("/api/mapping/decide/bulk", json={
        "cdm_name": cdm_name,
        "domain": "Condition",
        "action": "approved",
        "source_values": ["E11", "J45"],
    })
    assert resp.status_code == 200
    assert resp.json()["count"] == 1  # Only J45 was new


def test_decide_bulk_invalid_action(client, cdm_name):
    resp = client.post("/api/mapping/decide/bulk", json={
        "cdm_name": cdm_name,
        "domain": "Condition",
        "action": "modified",  # Not valid for bulk (pattern: approved|rejected)
        "source_values": ["E11"],
    })
    assert resp.status_code == 422  # Pydantic pattern validation rejects 'modified' for bulk


# ──── History tests ────

def test_history_empty(client, cdm_name):
    resp = client.get(f"/api/mapping/history/{cdm_name}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_history_with_decisions(client, cdm_name):
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name, "domain": "Condition",
        "source_value": "E11", "action": "approved", "target_concept_id": 201826,
    })
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name, "domain": "Drug",
        "source_value": "METFORMIN", "action": "rejected",
    })

    resp = client.get(f"/api/mapping/history/{cdm_name}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


def test_history_filter_by_domain(client, cdm_name):
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name, "domain": "Condition",
        "source_value": "E11", "action": "approved", "target_concept_id": 201826,
    })
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name, "domain": "Drug",
        "source_value": "METFORMIN", "action": "rejected",
    })

    resp = client.get(f"/api/mapping/history/{cdm_name}", params={"domain": "Condition"})
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["domain"] == "Condition"


def test_history_filter_by_status(client, cdm_name):
    """Status filter is consensus-aware: approved-without-2-users shows as 'pending',
    not 'approved'."""
    # E11: approved by ONE user → displays as pending
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name, "domain": "Condition",
        "source_value": "E11", "action": "approved", "target_concept_id": 201826,
    }, headers={"X-Test-Username": "u1"})
    # E12: approved by TWO users → consensus → displays as approved
    decide_e12 = {"cdm_name": cdm_name, "domain": "Condition",
                  "source_value": "E12", "action": "approved", "target_concept_id": 201827}
    client.post("/api/mapping/decide", json=decide_e12, headers={"X-Test-Username": "u1"})
    client.post("/api/mapping/decide", json=decide_e12, headers={"X-Test-Username": "u2"})
    # E13: rejected
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name, "domain": "Condition",
        "source_value": "E13", "action": "rejected",
    })

    rejected = client.get(f"/api/mapping/history/{cdm_name}", params={"status": "rejected"})
    assert {it["source_value"] for it in rejected.json()["items"]} == {"E13"}

    # pending = approved/modified WITHOUT consensus → E11 only
    pending = client.get(f"/api/mapping/history/{cdm_name}", params={"status": "pending"})
    sv_pending = {it["source_value"] for it in pending.json()["items"]}
    assert "E11" in sv_pending and "E12" not in sv_pending and "E13" not in sv_pending

    # approved = consensus only → E12 only, NOT the pending E11
    approved = client.get(f"/api/mapping/history/{cdm_name}", params={"status": "approved"})
    sv_approved = {it["source_value"] for it in approved.json()["items"]}
    assert "E12" in sv_approved and "E11" not in sv_approved


def test_history_pagination(client, cdm_name):
    # Create 5 decisions
    for i in range(5):
        client.post("/api/mapping/decide", json={
            "cdm_name": cdm_name, "domain": "Condition",
            "source_value": f"CODE_{i}", "action": "approved", "target_concept_id": i,
        })

    resp = client.get(f"/api/mapping/history/{cdm_name}", params={"page": 1, "page_size": 2})
    data = resp.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["total_pages"] == 3


# ──── Rollback tests ────

def test_rollback_decision(client, cdm_name):
    # Create a decision
    resp = client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name, "domain": "Condition",
        "source_value": "E11", "action": "approved", "target_concept_id": 201826,
    })
    decision_id = resp.json()["id"]

    # Rollback
    resp = client.post(f"/api/mapping/history/{decision_id}/rollback")
    assert resp.status_code == 200
    assert resp.json()["rolled_back"] is True
    assert resp.json()["original_id"] == decision_id

    # Original should be gone, but rollback entry exists in history
    history = client.get(f"/api/mapping/history/{cdm_name}")
    actions = [item["action"] for item in history.json()["items"]]
    assert "rolled_back" in actions


def test_rollback_nonexistent(client):
    resp = client.post("/api/mapping/history/9999/rollback")
    assert resp.status_code == 404


# ──── Apply tests ────

def test_apply_no_approved(client, cdm_name):
    resp = client.post("/api/mapping/apply", json={
        "cdm_name": cdm_name,
        "domain": "Condition",
    })
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_apply_with_approved_decisions(client, cdm_name):
    # Apply requires consensus (2+ users approve same mapping).
    # User 1 approves
    decide_e11 = {"cdm_name": cdm_name, "domain": "Condition",
        "source_value": "E11", "source_name": "Diabetes",
        "action": "approved", "target_concept_id": 201826,
        "target_concept_name": "Type 2 diabetes", "target_vocabulary_id": "SNOMED"}
    decide_j45 = {"cdm_name": cdm_name, "domain": "Condition",
        "source_value": "J45", "source_name": "Asthma",
        "action": "approved", "target_concept_id": 317009,
        "target_concept_name": "Asthma", "target_vocabulary_id": "SNOMED"}
    client.post("/api/mapping/decide", json=decide_e11, headers={"X-Test-Username": "user1"})
    client.post("/api/mapping/decide", json=decide_j45, headers={"X-Test-Username": "user1"})
    # User 2 approves same mappings → consensus
    client.post("/api/mapping/decide", json=decide_e11, headers={"X-Test-Username": "user2"})
    client.post("/api/mapping/decide", json=decide_j45, headers={"X-Test-Username": "user2"})
    # Add a rejected decision (should be ignored)
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name, "domain": "Condition",
        "source_value": "ZZZ", "action": "rejected",
    })

    resp = client.post("/api/mapping/apply", json={
        "cdm_name": cdm_name,
        "domain": "Condition",
        "write_to_cdm": False,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert data["written_to_cdm"] is False
    assert len(data["rows"]) == 2
    # Verify the apply response row structure (display rows for the UI)
    row = data["rows"][0]
    assert "source_code" in row
    assert "source_code_description" in row
    assert "target_concept_id" in row
    assert "target_vocabulary_id" in row


def test_apply_preview_no_decisions(client, cdm_name):
    resp = client.post("/api/mapping/apply/preview", json={
        "cdm_name": cdm_name,
        "domain": "Condition",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_decisions"] == 0
    # Preflight warnings shape is always present (empty when nothing to apply)
    assert body["warnings"]["counts"]["total_flagged"] == 0
    assert body["n_pushable_codes"] == 0


def test_compute_mapping_warnings_flags():
    """Preflight flags: A (1→N OPAL), B (already mapped in CDM), C (1→N in CDM)."""
    from types import SimpleNamespace
    from modules.mapping.router import (
        _compute_mapping_warnings,
        WARN_MULTIPLE_TARGETS_OPAL, WARN_ALREADY_MAPPED_CDM, WARN_MULTIPLE_CONCEPTS_CDM,
    )
    from tests.omop_mock import make_omop_conn

    decisions = [
        SimpleNamespace(source_value="OK1", target_concept_id=400, source_name="ok"),   # unmapped, single → pushable
        SimpleNamespace(source_value="I10", target_concept_id=100, source_name="hyp"),   # already mapped (B)
        SimpleNamespace(source_value="X", target_concept_id=200, source_name="x"),       # 1→N in CDM (B+C)
        SimpleNamespace(source_value="E11", target_concept_id=300, source_name="diab"),  # two OPAL targets (A)
        SimpleNamespace(source_value="E11", target_concept_id=301, source_name="diab"),
    ]
    conn = make_omop_conn([
        [  # the single COUNT(DISTINCT concept_id) query
            {"sv": "OK1", "n_concepts": 0},
            {"sv": "I10", "n_concepts": 1},
            {"sv": "X", "n_concepts": 2},
            {"sv": "E11", "n_concepts": 0},
        ],
    ])
    res = _compute_mapping_warnings(
        conn, "cdm.condition_occurrence", "condition_source_value", "condition_concept_id", decisions,
    )

    assert res["flagged"] == {"I10", "X", "E11"}
    assert "OK1" not in res["flagged"]  # only unmapped single-target code is pushable
    assert res["counts"][WARN_MULTIPLE_TARGETS_OPAL] == 1
    assert res["counts"][WARN_ALREADY_MAPPED_CDM] == 2
    assert res["counts"][WARN_MULTIPLE_CONCEPTS_CDM] == 1
    assert res["counts"]["total_flagged"] == 3
    e11 = next(i for i in res["items"] if i["source_value"] == "E11")
    assert WARN_MULTIPLE_TARGETS_OPAL in e11["flags"]
    assert e11["opal_targets"] == [300, 301]


def test_history_cdm_concepts_annotation(client):
    """/history annotates each row with cdm_concepts (distinct non-zero CDM concepts)
    from SourceValueCache → drives the 'already mapped' / 'multiple concepts' badges."""
    from tests.conftest import TestSession
    from db.models import MappingDecision, SourceValueCache

    cdm = "test_cdm_annot"
    db = TestSession()
    try:
        db.add_all([
            MappingDecision(cdm_name=cdm, domain="Condition", source_value="I10", action="approved", target_concept_id=111, user="u1"),
            MappingDecision(cdm_name=cdm, domain="Condition", source_value="E11", action="approved", target_concept_id=222, user="u1"),
            MappingDecision(cdm_name=cdm, domain="Condition", source_value="OK1", action="approved", target_concept_id=333, user="u1"),
            # I10 already mapped to TWO concepts in the CDM → cdm_concepts = 2 (red)
            SourceValueCache(cdm_name=cdm, domain="Condition", source_value="I10", n_records=5, n_persons=5, mapped_concept_id=900),
            SourceValueCache(cdm_name=cdm, domain="Condition", source_value="I10", n_records=3, n_persons=3, mapped_concept_id=901),
            # E11 mapped to ONE concept → cdm_concepts = 1 (orange)
            SourceValueCache(cdm_name=cdm, domain="Condition", source_value="E11", n_records=4, n_persons=4, mapped_concept_id=902),
            # OK1 unmapped (concept_id 0) → cdm_concepts = 0 (no badge)
            SourceValueCache(cdm_name=cdm, domain="Condition", source_value="OK1", n_records=2, n_persons=2, mapped_concept_id=0),
        ])
        db.commit()
    finally:
        db.close()

    resp = client.get(f"/api/mapping/history/{cdm}")
    assert resp.status_code == 200
    items = resp.json()["items"]
    by_sv = {it["source_value"]: it["cdm_concepts"] for it in items}
    by_ids = {it["source_value"]: it["cdm_concept_ids"] for it in items}
    assert by_sv["I10"] == 2 and by_ids["I10"] == [900, 901]
    assert by_sv["E11"] == 1 and by_ids["E11"] == [902]
    assert by_sv["OK1"] == 0 and by_ids["OK1"] == []


def test_mark_and_unmark_synced(client, cdm_name):
    """mark-synced flags only decisions whose CDM target == OPAL target (single concept).
    hide_synced then removes them from history; unmark-synced reverts."""
    from tests.conftest import TestSession
    from db.models import MappingDecision, SourceValueCache

    db = TestSession()
    try:
        db.add_all([
            MappingDecision(cdm_name=cdm_name, domain="Condition", source_value="I10", action="approved", target_concept_id=900, user="u1"),  # CDM=900 → synced
            MappingDecision(cdm_name=cdm_name, domain="Condition", source_value="E11", action="approved", target_concept_id=999, user="u1"),  # CDM=902 → divergent
            MappingDecision(cdm_name=cdm_name, domain="Condition", source_value="X", action="approved", target_concept_id=900, user="u1"),    # CDM={900,901} → 1→N
            SourceValueCache(cdm_name=cdm_name, domain="Condition", source_value="I10", n_records=1, n_persons=1, mapped_concept_id=900),
            SourceValueCache(cdm_name=cdm_name, domain="Condition", source_value="E11", n_records=1, n_persons=1, mapped_concept_id=902),
            SourceValueCache(cdm_name=cdm_name, domain="Condition", source_value="X", n_records=1, n_persons=1, mapped_concept_id=900),
            SourceValueCache(cdm_name=cdm_name, domain="Condition", source_value="X", n_records=1, n_persons=1, mapped_concept_id=901),
        ])
        db.commit()
    finally:
        db.close()

    # Only I10 qualifies (CDM holds exactly its target).
    resp = client.post("/api/mapping/decisions/mark-synced", json={"cdm_name": cdm_name, "domain": "Condition"})
    assert resp.status_code == 200
    assert resp.json()["marked"] == 1

    h = client.get(f"/api/mapping/history/{cdm_name}", params={"hide_synced": "true"})
    svs = {it["source_value"] for it in h.json()["items"]}
    assert "I10" not in svs and "E11" in svs and "X" in svs

    # I10 row carries synced=True when shown
    h_all = client.get(f"/api/mapping/history/{cdm_name}")
    i10 = next(it for it in h_all.json()["items"] if it["source_value"] == "I10")
    assert i10["synced"] is True

    # unmark reverts
    u = client.post("/api/mapping/decisions/unmark-synced", json={"cdm_name": cdm_name, "domain": "Condition"})
    assert u.json()["unmarked"] == 1
    h2 = client.get(f"/api/mapping/history/{cdm_name}", params={"hide_synced": "true"})
    assert "I10" in {it["source_value"] for it in h2.json()["items"]}


def test_redundant_svs_live():
    """Codes already correctly in the CDM (same single target) or synced are redundant
    → dropped from preview/export. Divergent / 1→N / unmapped are NOT redundant."""
    from types import SimpleNamespace
    from modules.mapping.router import _redundant_svs_live
    from tests.omop_mock import make_omop_conn

    decisions = [
        SimpleNamespace(source_value="SAME", target_concept_id=500, synced=0),     # CDM=500 → redundant
        SimpleNamespace(source_value="SYNCED", target_concept_id=600, synced=1),   # flag → redundant
        SimpleNamespace(source_value="DIFF", target_concept_id=700, synced=0),     # CDM=800 → keep
        SimpleNamespace(source_value="MULTI", target_concept_id=900, synced=0),    # CDM={900,901} → keep
        SimpleNamespace(source_value="UNMAPPED", target_concept_id=1000, synced=0),# CDM=∅ → keep
    ]
    conn = make_omop_conn([
        [
            {"sv": "SAME", "cid": 500},
            {"sv": "SYNCED", "cid": 600},
            {"sv": "DIFF", "cid": 800},
            {"sv": "MULTI", "cid": 900},
            {"sv": "MULTI", "cid": 901},
        ],
    ])
    redundant = _redundant_svs_live(conn, "cdm.condition_occurrence", "condition_source_value", "condition_concept_id", decisions)
    assert redundant == {"SAME", "SYNCED"}


# ──── Export tests ────

def test_export_stcm_csv(client, cdm_name):
    # Export requires consensus (2+ users approve same mapping)
    decide = {"cdm_name": cdm_name, "domain": "Condition",
        "source_value": "E11", "action": "approved",
        "target_concept_id": 201826, "target_vocabulary_id": "SNOMED"}
    client.post("/api/mapping/decide", json=decide, headers={"X-Test-Username": "user1"})
    client.post("/api/mapping/decide", json=decide, headers={"X-Test-Username": "user2"})

    resp = client.get(f"/api/mapping/apply/export/{cdm_name}/Condition")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    content = resp.text
    assert "sourceCode" in content  # STCM (Usagi) standard header
    assert "E11" in content
    assert "201826" in content


def test_export_stcm_empty(client, cdm_name):
    resp = client.get(f"/api/mapping/apply/export/{cdm_name}/Condition")
    assert resp.status_code == 200
    # Should have header but no data rows
    lines = resp.text.strip().split("\n")
    assert len(lines) == 1  # Header only


def test_export_history_csv(client, cdm_name):
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name, "domain": "Condition",
        "source_value": "E11", "action": "approved", "target_concept_id": 201826,
    })

    resp = client.get(f"/api/mapping/history/{cdm_name}/export")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    content = resp.text
    assert "source_value" in content
    assert "E11" in content


def test_export_history_filtered(client, cdm_name):
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name, "domain": "Condition",
        "source_value": "E11", "action": "approved", "target_concept_id": 201826,
    })
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name, "domain": "Drug",
        "source_value": "METFORMIN", "action": "rejected",
    })

    resp = client.get(f"/api/mapping/history/{cdm_name}/export", params={"domain": "Condition"})
    assert resp.status_code == 200
    content = resp.text
    assert "E11" in content
    assert "METFORMIN" not in content


# ──── i18n mapping translations ────

def test_i18n_mapping_en(client):
    resp = client.get("/api/i18n/en")
    assert resp.status_code == 200
    data = resp.json()
    assert "mapping" in data
    assert "dashboard" in data["mapping"]


def test_i18n_mapping_fr(client):
    resp = client.get("/api/i18n/fr")
    assert resp.status_code == 200
    data = resp.json()
    assert "mapping" in data
    assert data["mapping"]["dashboard"] == "Tableau de bord"
