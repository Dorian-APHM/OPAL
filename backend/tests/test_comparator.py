"""Tests for snapshot comparison logic."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.quality.comparator import compare_snapshots, _pct_change


def test_pct_change_basic():
    assert _pct_change(100, 110) == 10.0
    assert _pct_change(100, 90) == -10.0
    assert _pct_change(100, 100) == 0.0


def test_pct_change_edge_cases():
    assert _pct_change(0, 100) is None
    assert _pct_change(None, 100) is None
    assert _pct_change(100, None) is None


def test_compare_dashboard_no_change():
    snap_a = {
        "domain": "Dashboard",
        "summary": {
            "total_persons": 1000,
            "domains": [{"domain": "Condition", "total_records": 5000, "pct_terms_mapped": 80.0}]
        }
    }
    snap_b = {
        "domain": "Dashboard",
        "summary": {
            "total_persons": 1000,
            "domains": [{"domain": "Condition", "total_records": 5000, "pct_terms_mapped": 80.0}]
        }
    }
    result = compare_snapshots(snap_a, snap_b, threshold=5.0)
    assert result["domain"] == "Dashboard"
    assert len(result["alerts"]) == 0


def test_compare_dashboard_with_alert():
    snap_a = {
        "domain": "Dashboard",
        "summary": {
            "total_persons": 1000,
            "domains": [{"domain": "Condition", "total_records": 5000, "pct_terms_mapped": 80.0}]
        }
    }
    snap_b = {
        "domain": "Dashboard",
        "summary": {
            "total_persons": 800,
            "domains": [{"domain": "Condition", "total_records": 5000, "pct_terms_mapped": 70.0}]
        }
    }
    result = compare_snapshots(snap_a, snap_b, threshold=5.0)
    assert len(result["alerts"]) > 0
    # total_persons dropped 20%
    person_alert = [a for a in result["alerts"] if a["metric"] == "total_persons"]
    assert len(person_alert) == 1
    assert person_alert[0]["pct_change"] == -20.0


def test_compare_clinical():
    snap_a = {
        "domain": "Condition",
        "achilles_like": {"global": {"total_rows": 10000, "distinct_persons": 1000}},
        "mapping": {
            "terms": {"pct_terms_mapped": 90.0},
            "rows": {"pct_rows_mapped": 95.0}
        }
    }
    snap_b = {
        "domain": "Condition",
        "achilles_like": {"global": {"total_rows": 10000, "distinct_persons": 1000}},
        "mapping": {
            "terms": {"pct_terms_mapped": 80.0},
            "rows": {"pct_rows_mapped": 95.0}
        }
    }
    result = compare_snapshots(snap_a, snap_b, threshold=5.0)
    mapping_alert = [a for a in result["alerts"] if a["metric"] == "pct_terms_mapped"]
    assert len(mapping_alert) == 1


def test_compare_person():
    snap_a = {
        "domain": "Person",
        "achilles_like": {"person_summary": {"total_persons": 2400000}},
    }
    snap_b = {
        "domain": "Person",
        "achilles_like": {"person_summary": {"total_persons": 2400000}},
    }
    result = compare_snapshots(snap_a, snap_b, threshold=5.0)
    assert len(result["alerts"]) == 0


def test_compare_threshold_boundary():
    """Exactly at threshold should NOT alert."""
    snap_a = {
        "domain": "Person",
        "achilles_like": {"person_summary": {"total_persons": 100}},
    }
    snap_b = {
        "domain": "Person",
        "achilles_like": {"person_summary": {"total_persons": 105}},
    }
    result = compare_snapshots(snap_a, snap_b, threshold=5.0)
    assert len(result["alerts"]) == 0


def test_compare_above_threshold():
    """Just above threshold should alert."""
    snap_a = {
        "domain": "Person",
        "achilles_like": {"person_summary": {"total_persons": 100}},
    }
    snap_b = {
        "domain": "Person",
        "achilles_like": {"person_summary": {"total_persons": 106}},
    }
    result = compare_snapshots(snap_a, snap_b, threshold=5.0)
    assert len(result["alerts"]) == 1
