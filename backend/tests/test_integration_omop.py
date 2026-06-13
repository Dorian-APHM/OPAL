"""
Integration tests against a *real* PostgreSQL OMOP CDM.

These are the regression harness for the multi-engine connector port: they run
the actual endpoint SQL against a live database (not the mock cursor), so a SQL
rewrite can be proven byte-equivalent in behaviour.

Skipped unless a real OMOP PG is configured via OPAL_ITEST_OMOP_HOST. To run:

    # 1. seed a mini OMOP into a PostgreSQL reachable on a non-loopback address
    psql -h <host> -U opal -d postgres -f tests/fixtures/omop_mini_seed.sql
    # 2. run (host must be a non-loopback IP — the API blocks loopback for SSRF)
    OPAL_ITEST_OMOP_HOST=<host> OPAL_ITEST_OMOP_PORT=5432 \
    OPAL_ITEST_OMOP_DB=postgres OPAL_ITEST_OMOP_USER=opal \
    pytest tests/test_integration_omop.py -v

The expected schema/data is tests/fixtures/omop_mini_seed.sql: concepts
320128/201826/1503297/3004249, schema omop_cdm.
"""
import os
import pytest

OMOP_HOST = os.environ.get("OPAL_ITEST_OMOP_HOST")
pytestmark = pytest.mark.skipif(
    not OMOP_HOST, reason="real OMOP PG not configured (set OPAL_ITEST_OMOP_HOST)"
)


@pytest.fixture
def client():
    from tests.conftest import TestClient, app
    return TestClient(app)


@pytest.fixture
def cdm(client):
    client.post("/api/cdm/", json={
        "name": "itest_pg",
        "db_type": os.environ.get("OPAL_ITEST_OMOP_DBTYPE", "postgresql"),
        "db_host": OMOP_HOST,
        "db_port": int(os.environ.get("OPAL_ITEST_OMOP_PORT", "5599")),
        "db_name": os.environ.get("OPAL_ITEST_OMOP_DB", "postgres"),
        "db_user": os.environ.get("OPAL_ITEST_OMOP_USER", "opal"),
        "db_password": os.environ.get("OPAL_ITEST_OMOP_PASSWORD", "x"),
        "omop_schema": os.environ.get("OPAL_ITEST_OMOP_SCHEMA", "omop_cdm"),
    })
    return "itest_pg"


def test_search_by_text(client, cdm):
    r = client.get(f"/api/concepts/search?cdm_name={cdm}&q=hypertension")
    assert r.status_code == 200
    names = [c["concept_name"].lower() for c in r.json()["concepts"]]
    assert any("hypertension" in n for n in names)


def test_search_accent_insensitive(client, cdm):
    # 'diabete' (no accent, partial) must match 'Type 2 diabetes mellitus' via unaccent/ILIKE.
    r = client.get(f"/api/concepts/search?cdm_name={cdm}&q=diabet")
    assert r.status_code == 200
    assert any(c["concept_id"] == 201826 for c in r.json()["concepts"])


def test_search_by_code(client, cdm):
    r = client.get(f"/api/concepts/search?cdm_name={cdm}&q=59621000")
    assert r.status_code == 200
    assert any(c["concept_id"] == 320128 for c in r.json()["concepts"])


def test_search_with_domain_and_vocab_filter(client, cdm):
    r = client.get(f"/api/concepts/search?cdm_name={cdm}&q=metformin&domain=Drug&vocabulary=RxNorm")
    assert r.status_code == 200
    rows = r.json()["concepts"]
    assert rows and all(c["domain_id"] == "Drug" and c["vocabulary_id"] == "RxNorm" for c in rows)


def test_domains(client, cdm):
    r = client.get(f"/api/concepts/domains?cdm_name={cdm}")
    assert r.status_code == 200
    doms = {d["domain_id"] for d in r.json()["domains"]}
    assert {"Condition", "Drug", "Measurement"} <= doms


def test_vocabularies(client, cdm):
    r = client.get(f"/api/concepts/vocabularies?cdm_name={cdm}")
    assert r.status_code == 200
    vocs = {v["vocabulary_id"] for v in r.json()["vocabularies"]}
    assert {"SNOMED", "RxNorm", "LOINC"} <= vocs


def test_details_and_synonyms(client, cdm):
    r = client.get(f"/api/concepts/details/320128?cdm_name={cdm}")
    assert r.status_code == 200
    body = r.json()
    assert body["concept"]["concept_name"] == "Essential hypertension"
    assert any(s["concept_synonym_name"] == "High blood pressure" for s in body["synonyms"])


def test_details_not_found(client, cdm):
    r = client.get(f"/api/concepts/details/99999999?cdm_name={cdm}")
    assert r.status_code == 404
