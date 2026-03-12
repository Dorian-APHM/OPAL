"""Tests for Global Search endpoint."""
import pytest

from db.models import Cohort, MappingDecision, SavedQuery


def test_search_empty(client):
    resp = client.get("/api/search/", params={"q": "test"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_search_cohorts(client):
    # Create a cohort via the DB directly through the API
    from tests.conftest import TestSession
    db = TestSession()
    cohort = Cohort(cdm_name="test_cdm", name="Diabetes Cohort", description="T2D patients")
    db.add(cohort)
    db.commit()
    db.close()

    resp = client.get("/api/search/", params={"q": "Diabetes"})
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
    assert len(resp.json()["results"]["cohorts"]) >= 1
    assert resp.json()["results"]["cohorts"][0]["name"] == "Diabetes Cohort"


def test_search_saved_queries(client):
    from tests.conftest import TestSession
    db = TestSession()
    sq = SavedQuery(cdm_name="test_cdm", name="Patient Count Query", sql="SELECT COUNT(*) FROM person")
    db.add(sq)
    db.commit()
    db.close()

    resp = client.get("/api/search/", params={"q": "Patient Count"})
    assert resp.status_code == 200
    assert len(resp.json()["results"]["saved_queries"]) >= 1


def test_search_mappings(client):
    from tests.conftest import TestSession
    db = TestSession()
    md = MappingDecision(
        cdm_name="test_cdm", domain="Condition",
        source_value="hypertension_code", action="approved",
    )
    db.add(md)
    db.commit()
    db.close()

    resp = client.get("/api/search/", params={"q": "hypertension"})
    assert resp.status_code == 200
    assert len(resp.json()["results"]["mappings"]) >= 1


def test_search_with_cdm_filter(client):
    from tests.conftest import TestSession
    db = TestSession()
    db.add(Cohort(cdm_name="cdm_a", name="Alpha Cohort"))
    db.add(Cohort(cdm_name="cdm_b", name="Alpha Other"))
    db.commit()
    db.close()

    resp = client.get("/api/search/", params={"q": "Alpha", "cdm_name": "cdm_a"})
    assert resp.status_code == 200
    cohorts = resp.json()["results"]["cohorts"]
    assert len(cohorts) == 1
    assert cohorts[0]["cdm_name"] == "cdm_a"


def test_search_min_query(client):
    resp = client.get("/api/search/", params={"q": ""})
    assert resp.status_code == 422  # validation error for min_length
