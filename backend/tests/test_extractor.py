"""Tests for datamanagement/extractor.py — Dataset extraction SQL builder."""
import pytest
from modules.datamanagement.extractor import (
    _safe, _agg_expr, build_extraction_sql, EXTRACTABLE_TABLES,
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
        with pytest.raises(ValueError):
            _safe("table; DROP--")
        with pytest.raises(ValueError):
            _safe("with spaces")
        with pytest.raises(ValueError):
            _safe("123_starts_with_digit")
        with pytest.raises(ValueError):
            _safe("")


# ── _agg_expr ──

class TestAggExpr:
    def test_returns_string_agg(self):
        result = _agg_expr("condition_concept_id")
        assert "string_agg" in result
        assert "DISTINCT" in result
        assert "condition_concept_id" in result

    def test_validates_column(self):
        with pytest.raises(ValueError):
            _agg_expr("bad column name")


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
        result = get_table_columns(conn, "omop_cdm", "nonexistent")
        assert result == []

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
                {"table_name": "concept"},  # not extractable
                {"table_name": "vocabulary"},  # not extractable
            ],
        ])
        result = list_available_tables(conn, "omop_cdm")
        assert "person" in result
        assert "visit_occurrence" in result
        assert "condition_occurrence" in result
        assert "concept" not in result
        assert "vocabulary" not in result

    def test_empty_schema(self):
        conn = make_omop_conn([[]])
        result = list_available_tables(conn, "omop_cdm")
        assert result == []


# ── build_extraction_sql ──

class TestBuildExtractionSql:
    def test_empty_selections_raises(self):
        with pytest.raises(ValueError, match="No tables selected"):
            build_extraction_sql("SELECT 1", "omop_cdm", [], False, False)

    def test_single_direct_table(self):
        """Extracting person columns should produce a direct join."""
        sql = build_extraction_sql(
            "SELECT person_id FROM omop_cdm.person",
            "omop_cdm",
            [{"table": "person", "columns": ["person_id", "year_of_birth", "gender_concept_id"]}],
            same_visit_only=False,
            cohort_has_visit=False,
        )
        assert "WITH cohort AS" in sql
        assert "base AS" in sql
        assert "year_of_birth" in sql
        assert "gender_concept_id" in sql
        assert "LEFT JOIN omop_cdm.person" in sql

    def test_clinical_table_aggregated(self):
        """Clinical tables should be pre-aggregated."""
        sql = build_extraction_sql(
            "SELECT person_id FROM cohort",
            "omop_cdm",
            [{"table": "condition_occurrence",
              "columns": ["person_id", "visit_occurrence_id", "condition_concept_id"]}],
            same_visit_only=False,
            cohort_has_visit=False,
        )
        assert "agg_condition_occurrence" in sql
        assert "string_agg" in sql.lower() or "GROUP BY" in sql

    def test_same_visit_filter(self):
        """same_visit_only uses cohort visit IDs directly."""
        sql = build_extraction_sql(
            "SELECT person_id, visit_occurrence_id FROM cohort",
            "omop_cdm",
            [{"table": "visit_occurrence",
              "columns": ["visit_occurrence_id", "visit_start_date"]}],
            same_visit_only=True,
            cohort_has_visit=True,
        )
        assert "WHERE c.visit_occurrence_id IS NOT NULL" in sql

    def test_multiple_tables(self):
        """Multiple tables produce correct JOINs."""
        sql = build_extraction_sql(
            "SELECT person_id FROM cohort",
            "omop_cdm",
            [
                {"table": "person", "columns": ["person_id", "year_of_birth"]},
                {"table": "condition_occurrence",
                 "columns": ["person_id", "visit_occurrence_id", "condition_concept_id"]},
            ],
            same_visit_only=False,
            cohort_has_visit=False,
        )
        assert "LEFT JOIN omop_cdm.person" in sql
        assert "agg_condition_occurrence" in sql

    def test_invalid_identifier_raises(self):
        with pytest.raises(ValueError):
            build_extraction_sql(
                "SELECT 1", "omop_cdm",
                [{"table": "valid_table", "columns": ["bad column"]}],
                False, False,
            )

    def test_only_join_keys_selected(self):
        """When only join keys are selected, a count column is added."""
        sql = build_extraction_sql(
            "SELECT person_id FROM cohort",
            "omop_cdm",
            [{"table": "condition_occurrence",
              "columns": ["person_id", "visit_occurrence_id"]}],
            same_visit_only=False,
            cohort_has_visit=False,
        )
        assert "count" in sql.lower()

    def test_order_by_present(self):
        sql = build_extraction_sql(
            "SELECT person_id FROM cohort",
            "omop_cdm",
            [{"table": "person", "columns": ["person_id", "year_of_birth"]}],
            same_visit_only=False,
            cohort_has_visit=False,
        )
        assert "ORDER BY" in sql
