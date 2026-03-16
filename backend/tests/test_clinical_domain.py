"""Tests for quality/domains/clinical.py — Clinical domain analysis helpers."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import date
from tests.omop_mock import make_omop_conn, MockCursor, DictRow


# ── Helper function tests ──

class TestGetGlobalStats:
    def test_basic(self):
        from modules.quality.domains.clinical import _get_global_stats
        cursor = MockCursor([
            {"total_rows": 5000},
            {"distinct_persons": 200},
        ])
        result = _get_global_stats(cursor, "omop_cdm", "condition_occurrence", "person_id")
        assert result["total_rows"] == 5000
        assert result["distinct_persons"] == 200

    def test_zero_rows(self):
        from modules.quality.domains.clinical import _get_global_stats
        cursor = MockCursor([
            {"total_rows": 0},
            {"distinct_persons": 0},
        ])
        result = _get_global_stats(cursor, "omop_cdm", "condition_occurrence", "person_id")
        assert result["total_rows"] == 0
        assert result["distinct_persons"] == 0

    def test_null_values(self):
        from modules.quality.domains.clinical import _get_global_stats
        cursor = MockCursor([
            {"total_rows": None},
            {"distinct_persons": None},
        ])
        result = _get_global_stats(cursor, "omop_cdm", "condition_occurrence", "person_id")
        assert result["total_rows"] == 0
        assert result["distinct_persons"] == 0


class TestGetMonthlyCountsm:
    def test_basic(self):
        from modules.quality.domains.clinical import _get_monthly_counts
        cursor = MockCursor([
            [
                {"month_start": date(2025, 1, 1), "n": 100},
                {"month_start": date(2025, 2, 1), "n": 150},
                {"month_start": date(2025, 3, 1), "n": 200},
            ],
        ])
        result = _get_monthly_counts(cursor, "omop_cdm", "condition_occurrence", "condition_start_date")
        assert result["month_start"] == ["2025-01-01", "2025-02-01", "2025-03-01"]
        assert result["count"] == [100, 150, 200]

    def test_empty(self):
        from modules.quality.domains.clinical import _get_monthly_counts
        cursor = MockCursor([[]])
        result = _get_monthly_counts(cursor, "omop_cdm", "condition_occurrence", "condition_start_date")
        assert result["month_start"] == []
        assert result["count"] == []


class TestGetRecordsPerPerson:
    def test_basic(self):
        from modules.quality.domains.clinical import _get_records_per_person
        cursor = MockCursor([
            [
                {"records_per_person": 1, "n_persons": 100},
                {"records_per_person": 2, "n_persons": 50},
                {"records_per_person": 5, "n_persons": 20},
            ],
        ])
        result = _get_records_per_person(cursor, "omop_cdm", "condition_occurrence", "person_id", max_bin=10)
        assert result["records_per_person"] == [1, 2, 5]
        assert result["n_persons"] == [100, 50, 20]
        assert result["max_bin"] == 10

    def test_bucketing(self):
        """Values above max_bin are bucketed together."""
        from modules.quality.domains.clinical import _get_records_per_person
        cursor = MockCursor([
            [
                {"records_per_person": 1, "n_persons": 100},
                {"records_per_person": 5, "n_persons": 50},
                {"records_per_person": 15, "n_persons": 20},
                {"records_per_person": 50, "n_persons": 10},
            ],
        ])
        result = _get_records_per_person(cursor, "omop_cdm", "condition_occurrence", "person_id", max_bin=10)
        assert 10 in result["records_per_person"]
        # 15 and 50 should be bucketed into max_bin=10
        idx = result["records_per_person"].index(10)
        assert result["n_persons"][idx] == 30  # 20 + 10

    def test_empty(self):
        from modules.quality.domains.clinical import _get_records_per_person
        cursor = MockCursor([[]])
        result = _get_records_per_person(cursor, "omop_cdm", "condition_occurrence", "person_id", max_bin=10)
        assert result["records_per_person"] == []


class TestGetTopConcepts:
    def test_basic(self):
        from modules.quality.domains.clinical import _get_top_concepts
        cursor = MockCursor([
            [
                {"concept_id": 201826, "concept_name": "Diabetes", "source_value": "E11.9, E11",
                 "n_records": 500, "n_persons": 100},
                {"concept_id": 316866, "concept_name": "Hypertension", "source_value": "I10",
                 "n_records": 300, "n_persons": 80},
            ],
        ])
        result = _get_top_concepts(
            cursor, "omop_cdm", "condition_occurrence",
            "condition_concept_id", "condition_source_value", limit=10
        )
        assert len(result) == 2
        assert result[0]["concept_name"] == "Diabetes"
        assert result[0]["n_records"] == 500
        assert result[1]["concept_id"] == "316866"

    def test_null_source_value(self):
        from modules.quality.domains.clinical import _get_top_concepts
        cursor = MockCursor([
            [{"concept_id": 100, "concept_name": "Test", "source_value": None,
              "n_records": 10, "n_persons": 5}],
        ])
        result = _get_top_concepts(
            cursor, "omop_cdm", "condition_occurrence",
            "condition_concept_id", "condition_source_value", limit=5
        )
        assert result[0]["source_value"] == ""


class TestGetMappingStats:
    def test_basic(self):
        from modules.quality.domains.clinical import _get_mapping_stats
        cursor = MockCursor([
            {"total_rows": 1000, "mapped_rows": 800, "total_terms": 100, "mapped_terms": 70},
            [
                {"source_val": "unmapped_code_1", "n": 50},
                {"source_val": "unmapped_code_2", "n": 30},
            ],
        ])
        result = _get_mapping_stats(
            cursor, "omop_cdm", "condition_occurrence",
            "condition_source_value", "condition_concept_id", top_unmapped=10
        )
        assert result["terms"]["total_terms"] == 100
        assert result["terms"]["mapped_terms"] == 70
        assert result["terms"]["unmapped_terms"] == 30
        assert result["rows"]["total_rows"] == 1000
        assert result["rows"]["mapped_rows"] == 800
        assert result["rows"]["pct_rows_mapped"] == 80.0
        assert len(result["top_unmapped_terms"]) == 2

    def test_with_source_name_col(self):
        from modules.quality.domains.clinical import _get_mapping_stats
        cursor = MockCursor([
            {"total_rows": 100, "mapped_rows": 50, "total_terms": 10, "mapped_terms": 5},
            [{"source_val": "X01", "source_name": "Unknown Disease X", "n": 20}],
        ])
        result = _get_mapping_stats(
            cursor, "omop_cdm", "condition_occurrence",
            "condition_source_value", "condition_concept_id",
            top_unmapped=5, source_name_col="condition_source_concept_name"
        )
        assert result["top_unmapped_terms"][0]["source_name"] == "Unknown Disease X"

    def test_zero_terms(self):
        from modules.quality.domains.clinical import _get_mapping_stats
        cursor = MockCursor([
            {"total_rows": 0, "mapped_rows": 0, "total_terms": 0, "mapped_terms": 0},
            [],
        ])
        result = _get_mapping_stats(
            cursor, "omop_cdm", "condition_occurrence",
            "condition_source_value", "condition_concept_id", top_unmapped=10
        )
        assert result["terms"]["pct_terms_mapped"] is None
        assert result["rows"]["pct_rows_mapped"] is None


# ── Main function test ──

class TestRunClinicalDomainAnalysis:
    def test_condition_domain(self):
        from modules.quality.domains.clinical import run_clinical_domain_analysis

        responses = [
            # global stats: total_rows
            {"total_rows": 5000},
            # global stats: distinct_persons
            {"distinct_persons": 200},
            # monthly counts
            [{"month_start": date(2025, 1, 1), "n": 100}],
            # records per person
            [{"records_per_person": 1, "n_persons": 100}, {"records_per_person": 2, "n_persons": 50}],
            # top concepts
            [{"concept_id": 201826, "concept_name": "Diabetes", "source_value": "E11",
              "n_records": 200, "n_persons": 50}],
            # mapping stats
            {"total_rows": 5000, "mapped_rows": 4000, "total_terms": 100, "mapped_terms": 80},
            # top unmapped
            [{"source_val": "unmapped1", "n": 50}],
        ]
        conn = make_omop_conn(responses)
        result = run_clinical_domain_analysis(conn, "Condition", "omop_cdm")

        assert result["domain"] == "Condition"
        assert result["achilles_like"]["global"]["total_rows"] == 5000
        assert len(result["achilles_like"]["top_concepts"]) == 1
        assert result["mapping"]["terms"]["total_terms"] == 100

    def test_unknown_domain_raises(self):
        from modules.quality.domains.clinical import run_clinical_domain_analysis
        conn = make_omop_conn([])
        with pytest.raises(ValueError, match="Unknown clinical domain"):
            run_clinical_domain_analysis(conn, "FakeDomain", "omop_cdm")

    def test_all_configured_domains(self):
        """Verify all DOMAIN_CONFIG entries can be passed to run_clinical_domain_analysis."""
        from modules.quality.domains.clinical import run_clinical_domain_analysis
        from config import DOMAIN_CONFIG

        for domain_name in DOMAIN_CONFIG:
            responses = [
                {"total_rows": 10}, {"distinct_persons": 5},
                [], [], [],
                {"total_rows": 10, "mapped_rows": 8, "total_terms": 3, "mapped_terms": 2},
                [],
            ]
            conn = make_omop_conn(responses)
            result = run_clinical_domain_analysis(conn, domain_name, "omop_cdm")
            assert result["domain"] == domain_name
