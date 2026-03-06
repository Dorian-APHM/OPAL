"""
CDM comparison and regression detection.
Compares two analysis snapshots and highlights significant differences.
"""
from config import DEFAULT_COMPARISON_ALERT_THRESHOLD


def compare_snapshots(snapshot_a: dict, snapshot_b: dict,
                      threshold: float = DEFAULT_COMPARISON_ALERT_THRESHOLD) -> dict:
    """
    Compare two analysis snapshots and produce a diff with alerts.

    Args:
        snapshot_a: First snapshot results (reference).
        snapshot_b: Second snapshot results (comparison target).
        threshold: Percentage deviation that triggers an alert.

    Returns:
        Dict with comparison results and alerts.
    """
    alerts = []
    diffs = {}

    domain = snapshot_a.get("domain", "Unknown")

    if domain == "Dashboard":
        diffs, alerts = _compare_dashboard(snapshot_a, snapshot_b, threshold)
    elif domain == "Person":
        diffs, alerts = _compare_person(snapshot_a, snapshot_b, threshold)
    elif domain == "ObservationPeriod":
        diffs, alerts = _compare_observation_period(snapshot_a, snapshot_b, threshold)
    else:
        diffs, alerts = _compare_clinical(snapshot_a, snapshot_b, threshold)

    return {
        "domain": domain,
        "diffs": diffs,
        "alerts": alerts,
        "threshold": threshold,
    }


def _pct_change(a: float | int | None, b: float | int | None) -> float | None:
    """Calculate percentage change from a to b."""
    if a is None or b is None or a == 0:
        return None
    return ((b - a) / abs(a)) * 100


def _check_threshold(label: str, val_a, val_b, threshold: float,
                     alerts: list, diffs: dict) -> None:
    """Add a diff entry and alert if deviation exceeds threshold."""
    change = _pct_change(val_a, val_b)
    diffs[label] = {"a": val_a, "b": val_b, "pct_change": change}
    if change is not None and abs(change) > threshold:
        alerts.append({
            "metric": label,
            "value_a": val_a,
            "value_b": val_b,
            "pct_change": round(change, 2),
            "severity": "warning" if abs(change) <= threshold * 2 else "critical",
        })


def _compare_dashboard(a: dict, b: dict, threshold: float) -> tuple[dict, list]:
    alerts: list = []
    diffs: dict = {}
    sa = a.get("summary", {})
    sb = b.get("summary", {})

    _check_threshold("total_persons", sa.get("total_persons"), sb.get("total_persons"), threshold, alerts, diffs)

    domains_a = {d["domain"]: d for d in sa.get("domains", [])}
    domains_b = {d["domain"]: d for d in sb.get("domains", [])}
    for domain_name in set(domains_a) | set(domains_b):
        da = domains_a.get(domain_name, {})
        db = domains_b.get(domain_name, {})
        prefix = f"{domain_name}"
        _check_threshold(f"{prefix}.total_records", da.get("total_records"), db.get("total_records"), threshold, alerts, diffs)
        _check_threshold(f"{prefix}.pct_terms_mapped", da.get("pct_terms_mapped"), db.get("pct_terms_mapped"), threshold, alerts, diffs)

    return diffs, alerts


def _compare_person(a: dict, b: dict, threshold: float) -> tuple[dict, list]:
    alerts: list = []
    diffs: dict = {}
    pa = a.get("achilles_like", {}).get("person_summary", {})
    pb = b.get("achilles_like", {}).get("person_summary", {})
    _check_threshold("total_persons", pa.get("total_persons"), pb.get("total_persons"), threshold, alerts, diffs)
    return diffs, alerts


def _compare_observation_period(a: dict, b: dict, threshold: float) -> tuple[dict, list]:
    alerts: list = []
    diffs: dict = {}
    return diffs, alerts


def _compare_clinical(a: dict, b: dict, threshold: float) -> tuple[dict, list]:
    alerts: list = []
    diffs: dict = {}
    ga = a.get("achilles_like", {}).get("global", {})
    gb = b.get("achilles_like", {}).get("global", {})
    _check_threshold("total_rows", ga.get("total_rows"), gb.get("total_rows"), threshold, alerts, diffs)
    _check_threshold("distinct_persons", ga.get("distinct_persons"), gb.get("distinct_persons"), threshold, alerts, diffs)

    ma = a.get("mapping", {}).get("terms", {})
    mb = b.get("mapping", {}).get("terms", {})
    _check_threshold("pct_terms_mapped", ma.get("pct_terms_mapped"), mb.get("pct_terms_mapped"), threshold, alerts, diffs)

    ra = a.get("mapping", {}).get("rows", {})
    rb = b.get("mapping", {}).get("rows", {})
    _check_threshold("pct_rows_mapped", ra.get("pct_rows_mapped"), rb.get("pct_rows_mapped"), threshold, alerts, diffs)

    return diffs, alerts
