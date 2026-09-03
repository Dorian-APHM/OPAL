"""End-to-end checks: the reused engines run through the standalone bridge.

The CDM connection is the backend's own test mock, so these run without a
database and prove the shims cover everything the engines touch at run time.
"""
import pytest

from modules.quality.comparator import compare_snapshots
from modules.quality.engine import get_available_domains, run_domain_analysis
from modules.quality.report_builder import build_html_report
from tests.omop_mock import make_omop_conn  # backend/tests, on sys.path via the bridge
from utils.cdm_helper import SchemaMap


@pytest.fixture
def schema():
    return SchemaMap("omop_cdm", {"vocabulary": "omop_vocab"})


def test_person_analysis_runs_against_a_mock_connection(schema):
    conn = make_omop_conn([
        {"n": 3},                                                     # total persons
        [{"gender_concept_id": 8532, "concept_name": "FEMALE", "n": 2}],
        [{"year_of_birth": 1980, "n": 3}],
        [{"race_concept_id": 0, "concept_name": "UNKNOWN", "n": 3}],
        [{"ethnicity_concept_id": 0, "concept_name": "UNKNOWN", "n": 3}],
    ])
    result = run_domain_analysis(conn, "Person", omop_schema=schema)
    summary = result["achilles_like"]["person_summary"]

    assert result["table"] == "omop_cdm.person"
    assert summary["total_persons"] == 3
    assert summary["gender_distribution"]["gender_name"] == ["FEMALE"]
    assert summary["birth_year_distribution"]["year_of_birth"] == [1980]


def test_available_domains_filters_on_existing_tables(schema):
    # Every information_schema probe returns a row → all domains are offered.
    conn = make_omop_conn([{"exists": 1}] * 20)
    domains = get_available_domains(conn, schema)
    assert domains[:3] == ["Dashboard", "Person", "ObservationPeriod"]
    assert "Condition" in domains


def test_unknown_domain_is_rejected(schema):
    with pytest.raises(ValueError):
        run_domain_analysis(make_omop_conn([]), "NotADomain", omop_schema=schema)


def test_comparator_and_report_builder_work_on_snapshots():
    snapshot_a = {
        "domain": "Dashboard",
        "summary": {"total_persons": 100, "domains": [
            {"domain": "Condition", "total_records": 1000, "distinct_persons": 90,
             "pct_persons": 90.0, "total_terms": 50, "mapped_terms": 45,
             "unmapped_terms": 5, "pct_terms_mapped": 90.0},
        ]},
    }
    snapshot_b = {
        "domain": "Dashboard",
        "summary": {"total_persons": 150, "domains": [
            {"domain": "Condition", "total_records": 1500, "distinct_persons": 140,
             "pct_persons": 93.3, "total_terms": 60, "mapped_terms": 40,
             "unmapped_terms": 20, "pct_terms_mapped": 66.7},
        ]},
    }
    comparison = compare_snapshots(snapshot_a, snapshot_b, threshold=5.0)
    assert comparison["domain"] == "Dashboard"
    assert comparison["alerts"], "a 50 % jump in persons must raise an alert"

    html = build_html_report(
        "test-cdm",
        {"Dashboard": {"version": 1, "created_at": "2026-01-01", "results": snapshot_a}},
        lang="fr",
    )
    assert "test-cdm" in html and "<html" in html.lower()
