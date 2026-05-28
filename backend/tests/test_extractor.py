"""Tests for datamanagement/extractor.py — per-table raw extraction SQL + BDR schema."""
import pytest
from modules.datamanagement.extractor import (
    _safe, build_table_sql, build_schema, EXTRACTABLE_TABLES,
    get_table_columns, list_available_tables,
)
from tests.omop_mock import make_omop_conn


# ── _safe identifier validation ──

class TestSafe:
    def test_valid_identifiers(self):
        assert _safe("person") == "person"
        assert _safe("omop_cdm") == "omop_cdm"
        assert _safe("Table_123") == "Table_123"

    def test_rejects_injection(self):
        for bad in ("table; DROP--", "with spaces", "123_starts_with_digit", ""):
            with pytest.raises(ValueError):
                _safe(bad)


# ── EXTRACTABLE_TABLES constant ──

class TestExtractableTables:
    def test_has_required_tables(self):
        expected = {"person", "visit_occurrence", "condition_occurrence",
                    "drug_exposure", "measurement", "observation",
                    "procedure_occurrence", "device_exposure", "death",
                    "observation_period"}
        assert set(EXTRACTABLE_TABLES.keys()) == expected

    def test_person_no_visit(self):
        assert EXTRACTABLE_TABLES["person"]["has_visit"] is False

    def test_clinical_has_visit(self):
        for tbl in ("condition_occurrence", "drug_exposure", "measurement"):
            assert EXTRACTABLE_TABLES[tbl]["has_visit"] is True
            assert "visit_col" in EXTRACTABLE_TABLES[tbl]


# ── get_table_columns ──

class TestGetTableColumns:
    def test_basic(self):
        conn = make_omop_conn([
            [
                {"column_name": "person_id", "data_type": "integer"},
                {"column_name": "condition_concept_id", "data_type": "integer"},
                {"column_name": "condition_start_date", "data_type": "date"},
            ],
        ])
        result = get_table_columns(conn, "omop_cdm", "condition_occurrence")
        assert len(result) == 3
        assert result[0]["column_name"] == "person_id"

    def test_empty(self):
        conn = make_omop_conn([[]])
        assert get_table_columns(conn, "omop_cdm", "nonexistent") == []

    def test_invalid_schema(self):
        with pytest.raises(ValueError):
            get_table_columns(make_omop_conn([]), "bad schema", "person")


# ── list_available_tables ──

class TestListAvailableTables:
    def test_filters_to_extractable(self):
        conn = make_omop_conn([
            [
                {"table_name": "person"},
                {"table_name": "visit_occurrence"},
                {"table_name": "condition_occurrence"},
                {"table_name": "concept"},      # not extractable
                {"table_name": "vocabulary"},   # not extractable
            ],
        ])
        result = list_available_tables(conn, "omop_cdm")
        assert {"person", "visit_occurrence", "condition_occurrence"} <= set(result)
        assert "concept" not in result and "vocabulary" not in result

    def test_empty_schema(self):
        assert list_available_tables(make_omop_conn([[]]), "omop_cdm") == []


# ── build_table_sql (per-table raw extraction) ──

class TestBuildTableSql:
    def test_person_direct_join(self):
        sql = build_table_sql(
            "SELECT person_id FROM omop_cdm.person", "omop_cdm", "person",
            ["person_id", "year_of_birth", "gender_concept_id"],
            same_visit_only=False, cohort_has_visit=False,
        )
        assert "WITH cohort AS" in sql
        assert "FROM omop_cdm.person t" in sql
        assert "t.year_of_birth" in sql and "t.gender_concept_id" in sql
        assert "t.person_id IN (SELECT DISTINCT person_id FROM cohort)" in sql
        assert "ORDER BY t.person_id" in sql

    def test_clinical_person_filter(self):
        sql = build_table_sql(
            "SELECT person_id FROM cohort", "omop_cdm", "condition_occurrence",
            ["person_id", "condition_concept_id"],
            same_visit_only=False, cohort_has_visit=False,
        )
        assert "FROM omop_cdm.condition_occurrence t" in sql
        assert "t.person_id IN (SELECT DISTINCT person_id FROM cohort)" in sql

    def test_clinical_same_visit_filter(self):
        sql = build_table_sql(
            "SELECT person_id, visit_occurrence_id FROM cohort", "omop_cdm",
            "condition_occurrence", ["condition_concept_id"],
            same_visit_only=True, cohort_has_visit=True,
        )
        assert "(t.person_id, t.visit_occurrence_id) IN" in sql
        assert "visit_occurrence_id IS NOT NULL" in sql

    def test_invalid_column_raises(self):
        with pytest.raises(ValueError):
            build_table_sql("SELECT 1", "omop_cdm", "person", ["bad column"], False, False)

    def test_unknown_table_raises(self):
        with pytest.raises(ValueError, match="Unknown table"):
            build_table_sql("SELECT 1", "omop_cdm", "concept", ["concept_id"], False, False)

    def test_invalid_schema_raises(self):
        with pytest.raises(ValueError):
            build_table_sql("SELECT 1", "bad schema", "person", ["person_id"], False, False)


# ── build_schema (BDR relational schema) ──

class TestBuildSchema:
    def test_tables_and_pk(self):
        schema = build_schema([
            {"table": "person", "columns": ["person_id", "year_of_birth"]},
            {"table": "visit_occurrence", "columns": ["visit_occurrence_id", "person_id"]},
            {"table": "condition_occurrence", "columns": ["person_id", "condition_concept_id"]},
        ])
        by_name = {t["name"]: t for t in schema["tables"]}
        assert by_name["person"]["pk"] == "person_id"
        assert by_name["visit_occurrence"]["pk"] == "visit_occurrence_id"
        assert by_name["condition_occurrence"]["pk"] == "condition_occurrence_id"

    def test_relationships_on_shared_keys(self):
        schema = build_schema([
            {"table": "person", "columns": ["person_id"]},
            {"table": "condition_occurrence", "columns": ["person_id", "condition_concept_id"]},
        ])
        rels = schema["relationships"]
        assert any(
            r["from_column"] == "person_id" and r["to_column"] == "person_id"
            and {r["from_table"], r["to_table"]} == {"person", "condition_occurrence"}
            for r in rels
        )

    def test_with_all_columns_includes_data_type_and_selected(self):
        schema = build_schema(
            [{"table": "person", "columns": ["person_id"]}],
            all_columns={"person": [
                {"column_name": "person_id", "data_type": "integer"},
                {"column_name": "year_of_birth", "data_type": "integer"},
            ]},
        )
        cols = {c["name"]: c for c in schema["tables"][0]["columns"]}
        assert cols["person_id"]["data_type"] == "integer"
        assert cols["person_id"]["selected"] is True
        assert cols["year_of_birth"]["selected"] is False
