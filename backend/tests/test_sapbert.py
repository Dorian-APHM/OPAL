"""Tests for the in-app SapBERT API + suggestion scoping (per CDM + toggle)."""
from sqlalchemy.orm import sessionmaker

import db.app_db as _app_db
from db.models import SapbertDomainState, SapbertMapping
from modules.mapping.router import _get_sapbert_suggestions

_Session = sessionmaker(bind=_app_db.engine)


def test_config_endpoint(client):
    r = client.get("/api/sapbert/config")
    assert r.status_code == 200
    assert "enabled" in r.json()


def test_domains_and_toggle(client):
    db = _Session()
    db.add(SapbertDomainState(cdm_name="C", domain="Procedure", status="done",
                              row_count=3, enabled=True))
    db.commit(); db.close()

    r = client.get("/api/sapbert/domains/C")
    assert r.status_code == 200
    domains = r.json()["domains"]
    assert len(domains) == 1 and domains[0]["domain"] == "Procedure" and domains[0]["enabled"] is True

    r = client.put("/api/sapbert/toggle", json={"cdm_name": "C", "domain": "Procedure", "enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    # persisted
    assert client.get("/api/sapbert/domains/C").json()["domains"][0]["enabled"] is False

    # toggling a domain that was never built -> 404
    r = client.put("/api/sapbert/toggle", json={"cdm_name": "C", "domain": "Drug", "enabled": True})
    assert r.status_code == 404


def test_suggestion_scope():
    db = _Session()
    db.add(SapbertDomainState(cdm_name="C", domain="Procedure", status="done",
                              row_count=1, enabled=True))
    db.add(SapbertMapping(cdm_name="C", domain="Procedure", source_code="A", rank=1,
                          target_concept_id=111, target_concept_name="X", similarity=0.8))
    # legacy global row (no domain state for Condition)
    db.add(SapbertMapping(cdm_name=None, domain="Condition", source_code="B", rank=1,
                          target_concept_id=222, target_concept_name="Y", similarity=0.6))
    db.commit()

    # built + enabled -> per-CDM row
    s = _get_sapbert_suggestions(db, "A", "Procedure", "C")
    assert len(s) == 1 and s[0]["concept_id"] == 111 and s[0]["source"] == "sapbert"

    # toggle off -> nothing
    st = db.query(SapbertDomainState).filter_by(cdm_name="C", domain="Procedure").first()
    st.enabled = False
    db.commit()
    assert _get_sapbert_suggestions(db, "A", "Procedure", "C") == []

    # never built (Condition) -> legacy NULL-cdm rows still served
    s2 = _get_sapbert_suggestions(db, "B", "Condition", "C")
    assert len(s2) == 1 and s2[0]["concept_id"] == 222
    db.close()
