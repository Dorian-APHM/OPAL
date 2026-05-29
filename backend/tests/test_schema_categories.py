"""Tests for per-category OMOP schema configuration (SchemaMap + API)."""
import pytest

from utils.cdm_helper import SchemaMap, build_schema_map
from modules.cohort.sql_builder import build_cohort_sql


# ── SchemaMap unit behavior ──

def test_schema_map_default_behaves_like_string():
    sm = SchemaMap("omop_cdm")
    assert str(sm) == "omop_cdm"
    # No overrides → every table resolves to the default schema.
    assert sm.t("person") == "omop_cdm.person"
    assert sm.t("concept") == "omop_cdm.concept"


def test_schema_map_per_category_resolution():
    sm = SchemaMap("omop_cdm", {"vocabulary": "vocab", "clinical": "clin"})
    # clinical
    assert sm.t("person") == "clin.person"
    assert sm.t("drug_exposure") == "clin.drug_exposure"
    assert sm.schema_for("condition_occurrence") == "clin"
    # vocabulary
    assert sm.t("concept") == "vocab.concept"
    assert sm.t("concept_relationship") == "vocab.concept_relationship"
    assert sm.t("concept_ancestor") == "vocab.concept_ancestor"
    # category without override → default
    assert sm.t("payer_plan_period") == "omop_cdm.payer_plan_period"  # health_economics
    # unknown table → default
    assert sm.t("totally_unknown") == "omop_cdm.totally_unknown"


def test_schema_map_validates_identifiers():
    with pytest.raises(ValueError):
        SchemaMap("bad schema")
    with pytest.raises(ValueError):
        SchemaMap("omop_cdm", {"vocabulary": "bad;schema"})


def test_schema_map_empty_override_skipped():
    sm = SchemaMap("omop_cdm", {"vocabulary": "", "clinical": "clin"})
    assert sm.t("concept") == "omop_cdm.concept"
    assert sm.t("person") == "clin.person"


def test_build_schema_map_settings_override_config():
    class _Cdm:
        omop_schema = "cfg_default"
        schema_categories = {"vocabulary": "cfg_vocab", "clinical": "cfg_clin"}

    class _Settings:
        omop_schema = "set_default"
        schema_categories = {"vocabulary": "set_vocab"}

    sm = build_schema_map(_Cdm(), _Settings())
    assert str(sm) == "set_default"            # settings default wins
    assert sm.schema_for("concept") == "set_vocab"   # settings override wins
    assert sm.schema_for("person") == "cfg_clin"     # falls back to config override


# ── sql_builder integration ──

def test_build_cohort_sql_uses_category_schemas():
    sm = SchemaMap("omop_cdm", {"vocabulary": "vocab", "clinical": "clin"})
    criteria = {
        "inclusion": {
            "criteria": [
                {"domain": "Condition", "concepts": [{"concept_id": 201826}]}
            ]
        }
    }
    sql = build_cohort_sql(criteria, sm)
    # Clinical table from the clinical schema, vocabulary expansion from vocab schema.
    assert "clin.condition_occurrence" in sql
    if "concept_ancestor" in sql:
        assert "vocab.concept_ancestor" in sql
    assert "vocab.condition_occurrence" not in sql


def test_build_cohort_sql_plain_string_backward_compatible():
    criteria = {"inclusion": {"criteria": []}}
    sql = build_cohort_sql(criteria, "omop_cdm")
    assert "omop_cdm.person" in sql


# ── API endpoints ──

def test_categories_endpoint(client):
    resp = client.get("/api/cdm/categories")
    assert resp.status_code == 200
    data = resp.json()
    assert "vocabulary" in data["categories"]
    assert "clinical" in data["categories"]
    assert "concept" in data["tables"]["vocabulary"]
    assert "person" in data["tables"]["clinical"]


def test_create_cdm_with_schema_categories(client):
    resp = client.post("/api/cdm/", json={
        "name": "cat_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "test_db",
        "db_user": "test_user",
        "db_password": "test_pass",
        "omop_schema": "omop_cdm",
        "schema_categories": {"vocabulary": "shared_vocab"},
    })
    assert resp.status_code == 200, resp.text

    listed = client.get("/api/cdm/").json()["cdms"]
    cdm = next(c for c in listed if c["name"] == "cat_cdm")
    assert cdm["schema_categories"] == {"vocabulary": "shared_vocab"}


def test_create_cdm_rejects_unknown_category(client):
    resp = client.post("/api/cdm/", json={
        "name": "bad_cat_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "test_db",
        "db_user": "test_user",
        "db_password": "test_pass",
        "schema_categories": {"not_a_category": "x"},
    })
    assert resp.status_code == 422


def test_settings_round_trip_schema_categories(client):
    client.post("/api/cdm/", json={
        "name": "set_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "test_db",
        "db_user": "test_user",
        "db_password": "test_pass",
    })
    resp = client.put("/api/cdm/set_cdm/settings", json={
        "omop_schema": "omop_cdm",
        "schema_categories": {"vocabulary": "voc2"},
    })
    assert resp.status_code == 200, resp.text
    got = client.get("/api/cdm/set_cdm/settings").json()
    assert got["schema_categories"] == {"vocabulary": "voc2"}
