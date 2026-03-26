"""Tests for quality/domains/dashboard.py — Dashboard domain analysis."""
import pytest
from unittest.mock import patch
from tests.omop_mock import make_omop_conn


# A minimal DOMAIN_CONFIG used across tests to keep mock responses predictable.
_FAKE_CONFIG = {
    "Condition": {
        "table": "condition_occurrence",
        "person_id": "person_id",
        "concept_id": "condition_concept_id",
        "source_value": "condition_source_value",
        "date_col": "condition_start_date",
    },
    "Drug": {
        "table": "drug_exposure",
        "person_id": "person_id",
        "concept_id": "drug_concept_id",
        "source_value": "drug_source_value",
        "date_col": "drug_exposure_start_date",
    },
}


def _fake_get_domain_config(_conn, _schema, domain):
    """Return config directly from _FAKE_CONFIG without querying the database."""
    cfg = _FAKE_CONFIG.get(domain)
    return dict(cfg) if cfg else {}


def _build_responses(total, union_rows, sparklines=None, union_error=False, sparkline_error=False):
    """Build mock responses in the correct order for run_dashboard_analysis.

    Order of execute() calls:
      1. total persons
      2. information_schema.tables check per domain (one per domain)
      3. UNION ALL query
      4. sparkline query per domain with date_col
    """
    responses = [{"total": total}]
    # information_schema.tables — one per domain
    for _name in _FAKE_CONFIG:
        responses.append({"1": 1})  # truthy = table exists
    # UNION ALL
    if union_error:
        responses.append(Exception("relation does not exist"))
    else:
        responses.append(union_rows)
    # sparklines
    if sparklines is not None:
        responses.extend(sparklines)
    else:
        for name, cfg in _FAKE_CONFIG.items():
            if cfg.get("date_col"):
                if sparkline_error:
                    responses.append(Exception("timeout"))
                else:
                    responses.append([{"m": "2025-01-01", "n": 10}, {"m": "2025-02-01", "n": 15}])
    return responses


@patch("modules.quality.domains.dashboard.DOMAIN_CONFIG", _FAKE_CONFIG)
@patch("modules.quality.domains.dashboard.get_domain_config", _fake_get_domain_config)
def test_dashboard_basic():
    """Dashboard returns total_persons and domain stats."""
    from modules.quality.domains.dashboard import run_dashboard_analysis

    union_rows = [
        {"domain": "Condition", "total_records": 1000, "distinct_persons": 200,
         "total_terms": 50, "mapped_terms": 40},
        {"domain": "Drug", "total_records": 800, "distinct_persons": 150,
         "total_terms": 30, "mapped_terms": 25},
    ]
    responses = _build_responses(500, union_rows)
    conn = make_omop_conn(responses)
    result = run_dashboard_analysis(conn, "omop_cdm")

    assert result["domain"] == "Dashboard"
    assert result["summary"]["total_persons"] == 500
    assert isinstance(result["summary"]["domains"], list)
    assert len(result["summary"]["domains"]) == len(_FAKE_CONFIG)


@patch("modules.quality.domains.dashboard.DOMAIN_CONFIG", _FAKE_CONFIG)
@patch("modules.quality.domains.dashboard.get_domain_config", _fake_get_domain_config)
def test_dashboard_zero_persons():
    """Dashboard handles zero persons without division by zero."""
    from modules.quality.domains.dashboard import run_dashboard_analysis

    union_rows = [
        {"domain": d, "total_records": 0, "distinct_persons": 0,
         "total_terms": 0, "mapped_terms": 0} for d in _FAKE_CONFIG
    ]
    sparklines = [[] for _name, cfg in _FAKE_CONFIG.items() if cfg.get("date_col")]
    responses = _build_responses(0, union_rows, sparklines=sparklines)
    conn = make_omop_conn(responses)
    result = run_dashboard_analysis(conn, "omop_cdm")

    assert result["summary"]["total_persons"] == 0
    for ds in result["summary"]["domains"]:
        assert ds["pct_persons"] == 0
        assert ds["pct_terms_mapped"] == 0


@patch("modules.quality.domains.dashboard.DOMAIN_CONFIG", _FAKE_CONFIG)
@patch("modules.quality.domains.dashboard.get_domain_config", _fake_get_domain_config)
def test_dashboard_union_all_error_recovers():
    """Dashboard recovers gracefully when UNION ALL query fails."""
    from modules.quality.domains.dashboard import run_dashboard_analysis

    responses = _build_responses(100, [], union_error=True, sparkline_error=False)
    # When UNION ALL fails, domain_order is populated but stats_by_domain is empty.
    # No sparkline queries are run because domain_order entries have no stats -> fallback.
    # Actually, the code iterates domain_order and checks stats_by_domain.get(domain_name).
    # If missing, it appends a fallback entry (no sparkline query).
    # So we don't need sparkline responses when UNION fails and all domains fall through.
    # But the responses already include sparkline entries from _build_responses. That's fine;
    # they just won't be consumed.
    conn = make_omop_conn(responses)
    result = run_dashboard_analysis(conn, "omop_cdm")

    assert result["summary"]["total_persons"] == 100
    for ds in result["summary"]["domains"]:
        assert ds["total_records"] == 0 or "error" in ds


@patch("modules.quality.domains.dashboard.DOMAIN_CONFIG", _FAKE_CONFIG)
@patch("modules.quality.domains.dashboard.get_domain_config", _fake_get_domain_config)
def test_dashboard_sparkline_error_recovers():
    """Sparkline query failure doesn't crash the analysis."""
    from modules.quality.domains.dashboard import run_dashboard_analysis

    union_rows = [
        {"domain": d, "total_records": 10, "distinct_persons": 5,
         "total_terms": 3, "mapped_terms": 2} for d in _FAKE_CONFIG
    ]
    responses = _build_responses(100, union_rows, sparkline_error=True)
    conn = make_omop_conn(responses)
    result = run_dashboard_analysis(conn, "omop_cdm")

    assert len(result["summary"]["domains"]) > 0
    for ds in result["summary"]["domains"]:
        assert ds["sparkline"] == [] or isinstance(ds["sparkline"], list)


@patch("modules.quality.domains.dashboard.DOMAIN_CONFIG", _FAKE_CONFIG)
@patch("modules.quality.domains.dashboard.get_domain_config", _fake_get_domain_config)
def test_dashboard_mapping_percentages():
    """Verify mapping percentage calculations."""
    from modules.quality.domains.dashboard import run_dashboard_analysis

    # Only use Condition domain for this test
    single_config = {
        "Condition": _FAKE_CONFIG["Condition"],
    }

    def single_get_domain_config(_conn, _schema, domain):
        cfg = single_config.get(domain)
        return dict(cfg) if cfg else {}

    with patch("modules.quality.domains.dashboard.DOMAIN_CONFIG", single_config), \
         patch("modules.quality.domains.dashboard.get_domain_config", single_get_domain_config):
        responses = [
            {"total": 1000},
            {"1": 1},  # information_schema.tables for Condition
            [{"domain": "Condition", "total_records": 500, "distinct_persons": 100,
              "total_terms": 200, "mapped_terms": 150}],
            [{"m": "2025-01-01", "n": 5}],  # sparkline
        ]
        conn = make_omop_conn(responses)
        result = run_dashboard_analysis(conn, "omop_cdm")

    ds = result["summary"]["domains"][0]
    assert ds["pct_persons"] == 10.0  # 100/1000 * 100
    assert ds["pct_terms_mapped"] == 75.0  # 150/200 * 100
    assert ds["unmapped_terms"] == 50  # 200 - 150
