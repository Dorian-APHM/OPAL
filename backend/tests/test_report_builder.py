"""Tests for quality/report_builder.py — HTML report generation."""
import pytest


# ── Fixtures ──

def _make_dashboard_snapshot():
    return {
        "domain": "Dashboard",
        "summary": {
            "total_persons": 1000,
            "domains": [
                {
                    "domain": "Condition",
                    "total_records": 5000,
                    "distinct_persons": 200,
                    "pct_persons": 20.0,
                    "total_terms": 100,
                    "mapped_terms": 80,
                    "unmapped_terms": 20,
                    "pct_terms_mapped": 80.0,
                    "sparkline": [10, 20, 30],
                },
            ],
        },
    }


def _make_person_snapshot():
    return {
        "domain": "Person",
        "achilles_like": {
            "person_summary": {
                "total_persons": 1000,
                "gender_distribution": {
                    "gender_concept_id": [8507, 8532],
                    "gender_name": ["MALE", "FEMALE"],
                    "count": [600, 400],
                },
                "birth_year_distribution": {
                    "year_of_birth": [1980, 1990, 2000],
                    "count": [100, 200, 150],
                },
                "race_distribution": {
                    "race_concept_id": [], "race_name": [], "count": [],
                },
                "ethnicity_distribution": {
                    "ethnicity_concept_id": [], "ethnicity_name": [], "count": [],
                },
            },
        },
    }


def _make_clinical_snapshot(domain="Condition"):
    return {
        "domain": domain,
        "table": "omop_cdm.condition_occurrence",
        "achilles_like": {
            "global": {"total_rows": 5000, "distinct_persons": 200},
            "by_month": {"month_start": ["2025-01-01"], "count": [100]},
            "records_per_person": {
                "records_per_person": [1, 2, 3],
                "n_persons": [100, 50, 20],
                "max_bin": 50,
            },
            "top_concepts": [
                {"concept_id": "201826", "concept_name": "Diabetes",
                 "source_value": "E11", "n_records": 200, "n_persons": 50},
            ],
        },
        "mapping": {
            "terms": {"total_terms": 100, "mapped_terms": 80, "unmapped_terms": 20, "pct_terms_mapped": 80.0},
            "rows": {"total_rows": 5000, "mapped_rows": 4000, "unmapped_rows": 1000, "pct_rows_mapped": 80.0},
            "top_unmapped_terms": [{"source_value": "X01", "count": 50}],
        },
    }


# ── Tests ──

class TestBuildHtmlReport:
    def test_basic_report_en(self):
        from modules.quality.report_builder import build_html_report

        snapshots = {
            "Dashboard": {"version": 1, "created_at": "2025-01-01T00:00:00Z",
                          "results": _make_dashboard_snapshot()},
            "Person": {"version": 1, "created_at": "2025-01-01T00:00:00Z",
                       "results": _make_person_snapshot()},
            "Condition": {"version": 1, "created_at": "2025-01-01T00:00:00Z",
                          "results": _make_clinical_snapshot("Condition")},
        }
        html = build_html_report("test_cdm", snapshots, lang="en")

        assert "<!DOCTYPE html>" in html
        assert "OPAL Quality Report" in html
        assert "test_cdm" in html
        assert "Dashboard" in html
        assert "Person" in html
        assert "Condition" in html
        assert "Diabetes" in html

    def test_basic_report_fr(self):
        from modules.quality.report_builder import build_html_report

        snapshots = {
            "Dashboard": {"version": 1, "created_at": "2025-01-01T00:00:00Z",
                          "results": _make_dashboard_snapshot()},
        }
        html = build_html_report("test_cdm", snapshots, lang="fr")

        assert "Rapport Qualité OPAL" in html

    def test_empty_snapshots(self):
        from modules.quality.report_builder import build_html_report

        html = build_html_report("test_cdm", {}, lang="en")
        assert "<!DOCTYPE html>" in html

    def test_html_escaping(self):
        """XSS-safe: special characters in CDM name are escaped."""
        from modules.quality.report_builder import build_html_report

        html = build_html_report("<script>alert(1)</script>", {}, lang="en")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


class TestBuildComparisonReport:
    def test_basic_comparison(self):
        from modules.quality.report_builder import build_comparison_html_report

        comparisons = [
            {
                "domain": "Dashboard",
                "diffs": {"total_persons": {"a": 1000, "b": 1200, "pct_change": 20.0}},
                "alerts": [],
                "threshold": 10,
                "snap_a": {"version": 1},
                "snap_b": {"version": 2},
                "results_a": _make_dashboard_snapshot(),
                "results_b": _make_dashboard_snapshot(),
            },
        ]
        html = build_comparison_html_report("cdm_a", "cdm_b", comparisons, lang="en")

        assert "<!DOCTYPE html>" in html
        assert "cdm_a" in html
        assert "cdm_b" in html

    def test_comparison_with_alerts(self):
        from modules.quality.report_builder import build_comparison_html_report

        comparisons = [
            {
                "domain": "Dashboard",
                "diffs": {},
                "alerts": [
                    {"metric": "total_persons", "pct_change": -50.0,
                     "value_a": 1000, "value_b": 500,
                     "severity": "critical", "threshold": 20.0},
                ],
                "threshold": 10,
                "snap_a": {"version": 1},
                "snap_b": {"version": 2},
                "results_a": _make_dashboard_snapshot(),
                "results_b": _make_dashboard_snapshot(),
            },
        ]
        html = build_comparison_html_report("cdm_a", "cdm_b", comparisons, lang="en")
        assert "CRITICAL" in html

    def test_comparison_empty(self):
        from modules.quality.report_builder import build_comparison_html_report

        html = build_comparison_html_report("a", "b", [], lang="en")
        assert "<!DOCTYPE html>" in html


class TestSvgHelpers:
    def test_svg_bar_chart_overlay(self):
        from modules.quality.report_builder import _svg_bar_chart_overlay

        data_a = [("Jan", 100), ("Feb", 200)]
        data_b = [("Jan", 150), ("Feb", 180)]
        svg = _svg_bar_chart_overlay(data_a, data_b, "CDM A", "CDM B")
        assert "<svg" in svg
        assert "CDM A" in svg
        assert "CDM B" in svg

    def test_svg_bar_chart_empty(self):
        from modules.quality.report_builder import _svg_bar_chart_overlay

        svg = _svg_bar_chart_overlay([], [], "A", "B")
        # Empty data returns empty string
        assert svg == "" or "<svg" in svg

    def test_svg_donut_pair(self):
        from modules.quality.report_builder import _svg_donut_pair

        data_a = [("Male", 60), ("Female", 40)]
        data_b = [("Male", 55), ("Female", 45)]
        svg = _svg_donut_pair(data_a, data_b, "CDM A", "CDM B")
        assert "<svg" in svg

    def test_svg_donut_empty(self):
        from modules.quality.report_builder import _svg_donut_pair

        svg = _svg_donut_pair([], [], "A", "B")
        assert "<svg" in svg or svg == ""  # May return empty for no data
