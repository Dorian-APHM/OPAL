"""
Kaplan-Meier survival analysis — pure Python, no external dependencies.

Computes survival curves, confidence intervals (Greenwood), median survival,
and log-rank test between strata.
"""
import logging
from math import sqrt, exp

logger = logging.getLogger(__name__)


def compute_km(times: list[float], events: list[int]) -> list[dict]:
    """
    Compute Kaplan-Meier survival curve.

    Args:
        times: time-to-event (or censoring) for each subject
        events: 1 = event occurred, 0 = censored

    Returns:
        List of {time, survival, ci_lower, ci_upper, at_risk, events, censored}
    """
    if not times:
        return [{"time": 0, "survival": 1.0, "ci_lower": 1.0, "ci_upper": 1.0,
                 "at_risk": 0, "events": 0, "censored": 0}]

    n = len(times)

    # Build risk table: sorted unique event times
    # For each time point: number at risk, events, censored
    data = sorted(zip(times, events), key=lambda x: x[0])

    # Collect all unique event times (where events occurred)
    event_times = sorted(set(t for t, e in data if e == 1))

    survival = 1.0
    greenwood_sum = 0.0
    curve = [{"time": 0, "survival": 1.0, "ci_lower": 1.0, "ci_upper": 1.0,
              "at_risk": n, "events": 0, "censored": 0}]

    # Count subjects still at risk at each time
    remaining = list(data)  # sorted by time

    for t in event_times:
        # Number at risk: subjects with time >= t
        at_risk = sum(1 for ti, _ in remaining if ti >= t)
        if at_risk == 0:
            break

        # Events at this time
        events_at_t = sum(1 for ti, ei in remaining if ti == t and ei == 1)
        # Censored between previous event time and this time
        censored_at_t = sum(1 for ti, ei in remaining if ti == t and ei == 0)

        # KM estimate
        survival *= (1 - events_at_t / at_risk)

        # Greenwood's formula for variance
        if at_risk > events_at_t:
            greenwood_sum += events_at_t / (at_risk * (at_risk - events_at_t))

        # CI using log-log transformation for better coverage
        se = survival * sqrt(greenwood_sum) if greenwood_sum > 0 else 0
        z = 1.96
        ci_lower = max(0, survival - z * se)
        ci_upper = min(1, survival + z * se)

        curve.append({
            "time": t,
            "survival": round(survival, 6),
            "ci_lower": round(ci_lower, 6),
            "ci_upper": round(ci_upper, 6),
            "at_risk": at_risk,
            "events": events_at_t,
            "censored": censored_at_t,
        })

    return curve


def compute_median_survival(curve: list[dict]) -> float | None:
    """Find median survival time (time when survival crosses 0.5)."""
    for point in curve:
        if point["survival"] <= 0.5:
            return point["time"]
    return None


def log_rank_test(groups: dict[str, tuple[list[float], list[int]]]) -> dict:
    """
    Log-rank test comparing survival between groups.

    Args:
        groups: {group_name: (times, events)}

    Returns:
        {chi_square, p_value, df}
    """
    if len(groups) < 2:
        return {"chi_square": 0, "p_value": 1.0, "df": 0}

    group_names = list(groups.keys())
    all_data = {}
    for name, (times, events) in groups.items():
        all_data[name] = list(zip(times, events))

    # Get all unique event times across all groups
    all_event_times = sorted(set(
        t for name in group_names
        for t, e in all_data[name] if e == 1
    ))

    if not all_event_times:
        return {"chi_square": 0, "p_value": 1.0, "df": len(groups) - 1}

    # For each group, compute O (observed) and E (expected) events
    observed = {name: 0 for name in group_names}
    expected = {name: 0.0 for name in group_names}
    variance = {name: 0.0 for name in group_names}

    for t in all_event_times:
        # Number at risk in each group at time t
        n_risk = {}
        d_events = {}
        for name in group_names:
            n_risk[name] = sum(1 for ti, _ in all_data[name] if ti >= t)
            d_events[name] = sum(1 for ti, ei in all_data[name] if ti == t and ei == 1)

        total_risk = sum(n_risk.values())
        total_events = sum(d_events.values())

        if total_risk == 0:
            continue

        for name in group_names:
            observed[name] += d_events[name]
            e_i = n_risk[name] * total_events / total_risk
            expected[name] += e_i

            # Hypergeometric variance
            if total_risk > 1:
                v_i = (n_risk[name] * (total_risk - n_risk[name]) * total_events *
                       (total_risk - total_events)) / (total_risk ** 2 * (total_risk - 1))
                variance[name] += v_i

    # Chi-square statistic (using k-1 groups)
    chi2 = 0.0
    for name in group_names[:-1]:  # k-1 terms
        v = variance[name]
        if v > 0:
            chi2 += (observed[name] - expected[name]) ** 2 / v

    # p-value from chi-square distribution (approximation)
    df = len(groups) - 1
    p_value = _chi2_sf(chi2, df)

    return {
        "chi_square": round(chi2, 4),
        "p_value": round(p_value, 6),
        "df": df,
    }


def _chi2_sf(x: float, k: int) -> float:
    """Survival function of chi-square distribution (approximation)."""
    if x <= 0:
        return 1.0
    if k == 1:
        # Use normal approximation
        z = sqrt(x)
        return 2 * _norm_sf(z)
    if k == 2:
        return exp(-x / 2)

    # Wilson-Hilferty approximation for k >= 3
    z = ((x / k) ** (1 / 3) - (1 - 2 / (9 * k))) / sqrt(2 / (9 * k))
    return _norm_sf(z)


def _norm_sf(z: float) -> float:
    """Standard normal survival function (1 - CDF) approximation."""
    # Abramowitz and Stegun approximation
    if z < 0:
        return 1 - _norm_sf(-z)

    b1 = 0.319381530
    b2 = -0.356563782
    b3 = 1.781477937
    b4 = -1.821255978
    b5 = 1.330274429
    p = 0.2316419

    t = 1.0 / (1.0 + p * z)
    t2 = t * t
    t3 = t2 * t
    t4 = t3 * t
    t5 = t4 * t

    pdf = exp(-z * z / 2) / sqrt(2 * 3.141592653589793)
    return pdf * (b1 * t + b2 * t2 + b3 * t3 + b4 * t4 + b5 * t5)
