"""Tests for quality/domains/dashboard.py — Dashboard domain analysis."""
import pytest
from unittest.mock import patch
from tests.omop_mock import make_omop_conn


def test_dashboard_basic():
    """Dashboard returns total_persons and domain stats."""
    from modules.quality.domains.dashboard import run_dashboard_analysis

    # Response 1: total persons
    # Response 2: UNION ALL domain stats
    # Response 3+: sparkline queries (one per domain with date_col)
    responses = [
        {"total": 500},
        # UNION ALL results (fetchall)
        [
            {"domain": "Condition", "total_records": 1000, "distinct_persons": 200,
             "total_terms": 50, "mapped_terms": 40},
            {"domain": "Drug", "total_records": 800, "distinct_persons": 150,
             "total_terms": 30, "mapped_terms": 25},
        ],
    ]
    # Add sparkline responses for each domain that has a date_col
    from config import DOMAIN_CONFIG
    for name, cfg in DOMAIN_CONFIG.items():
        if cfg.get("date_col"):
            responses.append([{"m": "2025-01-01", "n": 10}, {"m": "2025-02-01", "n": 15}])

    conn = make_omop_conn(responses)
    result = run_dashboard_analysis(conn, "omop_cdm")

    assert result["domain"] == "Dashboard"
    assert result["summary"]["total_persons"] == 500
    assert isinstance(result["summary"]["domains"], list)
    assert len(result["summary"]["domains"]) == len(DOMAIN_CONFIG)


def test_dashboard_zero_persons():
    """Dashboard handles zero persons without division by zero."""
    from modules.quality.domains.dashboard import run_dashboard_analysis
    from config import DOMAIN_CONFIG

    responses = [
        {"total": 0},
        [{"domain": d, "total_records": 0, "distinct_persons": 0,
          "total_terms": 0, "mapped_terms": 0} for d in DOMAIN_CONFIG],
    ]
    for name, cfg in DOMAIN_CONFIG.items():
        if cfg.get("date_col"):
            responses.append([])

    conn = make_omop_conn(responses)
    result = run_dashboard_analysis(conn, "omop_cdm")

    assert result["summary"]["total_persons"] == 0
    for ds in result["summary"]["domains"]:
        assert ds["pct_persons"] == 0
        assert ds["pct_terms_mapped"] == 0


def test_dashboard_union_all_error_recovers():
    """Dashboard recovers gracefully when UNION ALL query fails."""
    from modules.quality.domains.dashboard import run_dashboard_analysis
    from config import DOMAIN_CONFIG

    responses = [
        {"total": 100},
        Exception("relation does not exist"),
    ]
    conn = make_omop_conn(responses)
    result = run_dashboard_analysis(conn, "omop_cdm")

    # All domains should show error / fallback
    assert result["summary"]["total_persons"] == 100
    for ds in result["summary"]["domains"]:
        assert ds["total_records"] == 0 or "error" in ds


def test_dashboard_sparkline_error_recovers():
    """Sparkline query failure doesn't crash the analysis."""
    from modules.quality.domains.dashboard import run_dashboard_analysis
    from config import DOMAIN_CONFIG

    responses = [
        {"total": 100},
        [{"domain": d, "total_records": 10, "distinct_persons": 5,
          "total_terms": 3, "mapped_terms": 2} for d in DOMAIN_CONFIG],
    ]
    # All sparkline queries fail
    for name, cfg in DOMAIN_CONFIG.items():
        if cfg.get("date_col"):
            responses.append(Exception("timeout"))

    conn = make_omop_conn(responses)
    result = run_dashboard_analysis(conn, "omop_cdm")

    # Should still have domains with empty sparklines
    assert len(result["summary"]["domains"]) > 0
    for ds in result["summary"]["domains"]:
        assert ds["sparkline"] == [] or isinstance(ds["sparkline"], list)


def test_dashboard_mapping_percentages():
    """Verify mapping percentage calculations."""
    from modules.quality.domains.dashboard import run_dashboard_analysis

    responses = [
        {"total": 1000},
        [
            {"domain": "Condition", "total_records": 500, "distinct_persons": 100,
             "total_terms": 200, "mapped_terms": 150},
        ],
    ]
    # Patch DOMAIN_CONFIG to have just one domain
    fake_config = {
        "Condition": {
            "table": "condition_occurrence", "person_id": "person_id",
            "concept_id": "condition_concept_id", "source_value": "condition_source_value",
            "date_col": "condition_start_date",
        }
    }
    with patch("modules.quality.domains.dashboard.DOMAIN_CONFIG", fake_config):
        responses.append([{"m": "2025-01-01", "n": 5}])  # sparkline
        conn = make_omop_conn(responses)
        result = run_dashboard_analysis(conn, "omop_cdm")

    ds = result["summary"]["domains"][0]
    assert ds["pct_persons"] == 10.0  # 100/1000 * 100
    assert ds["pct_terms_mapped"] == 75.0  # 150/200 * 100
    assert ds["unmapped_terms"] == 50  # 200 - 150
