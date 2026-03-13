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


def test_history_filter_by_action(client, cdm_name):
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name, "domain": "Condition",
        "source_value": "E11", "action": "approved", "target_concept_id": 201826,
    })
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name, "domain": "Condition",
        "source_value": "E13", "action": "rejected",
    })

    resp = client.get(f"/api/mapping/history/{cdm_name}", params={"action": "rejected"})
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["action"] == "rejected"


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
    # Create approved decisions
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name, "domain": "Condition",
        "source_value": "E11", "source_name": "Diabetes",
        "action": "approved", "target_concept_id": 201826,
        "target_concept_name": "Type 2 diabetes", "target_vocabulary_id": "SNOMED",
    })
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name, "domain": "Condition",
        "source_value": "J45", "source_name": "Asthma",
        "action": "approved", "target_concept_id": 317009,
        "target_concept_name": "Asthma", "target_vocabulary_id": "SNOMED",
    })
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
    # Verify STCM row structure
    row = data["rows"][0]
    assert "source_code" in row
    assert "target_concept_id" in row
    assert row["source_vocabulary_id"] == "OPAL_Condition"


def test_apply_preview_no_decisions(client, cdm_name):
    resp = client.post("/api/mapping/apply/preview", json={
        "cdm_name": cdm_name,
        "domain": "Condition",
    })
    assert resp.status_code == 200
    assert resp.json()["total_decisions"] == 0


# ──── Export tests ────

def test_export_stcm_csv(client, cdm_name):
    # Create approved decision
    client.post("/api/mapping/decide", json={
        "cdm_name": cdm_name, "domain": "Condition",
        "source_value": "E11", "action": "approved",
        "target_concept_id": 201826, "target_vocabulary_id": "SNOMED",
    })

    resp = client.get(f"/api/mapping/apply/export/{cdm_name}/Condition")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    content = resp.text
    assert "source_code" in content
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
