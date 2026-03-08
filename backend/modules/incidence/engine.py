"""
Incidence Rate calculation engine.

Computes incidence rates from a target cohort (population at risk) and an
outcome cohort (event of interest), using observation_period for time-at-risk.
"""
import logging
from math import sqrt, log

logger = logging.getLogger(__name__)


def build_incidence_sql(
    target_sql: str,
    outcome_sql: str,
    omop_schema: str,
    time_at_risk_start: int = 0,
    time_at_risk_end: str | int = "observation_end",
    strata: list[str] | None = None,
    age_groups: list[dict] | None = None,
    clean_window: int = 0,
) -> str:
    """
    Build SQL to compute incidence rate data.

    Returns individual-level data with time and outcome status
    for aggregation in Python (allows flexible stratification).
    """
    # Determine TAR end expression
    if time_at_risk_end == "observation_end" or time_at_risk_end is None:
        tar_end_expr = "op.observation_period_end_date"
    else:
        tar_end_expr = f"LEAST(op.observation_period_end_date, ce.cohort_start + INTERVAL '{int(time_at_risk_end)} days')"

    tar_start_expr = f"ce.cohort_start + INTERVAL '{int(time_at_risk_start)} days'"

    # Clean window filter: exclude patients with outcome before TAR start
    clean_filter = ""
    if clean_window > 0:
        clean_filter = (
            f"  AND NOT EXISTS (\n"
            f"    SELECT 1 FROM outcome_raw oex\n"
            f"    WHERE oex.person_id = ce.person_id\n"
            f"      AND oex.outcome_date < {tar_start_expr}\n"
            f"      AND oex.outcome_date >= ce.cohort_start - INTERVAL '{int(clean_window)} days'\n"
            f"  )\n"
        )

    sql = f"""
WITH target_raw AS (
    {target_sql}
),
cohort_entry AS (
    SELECT person_id, MIN(cohort_start_date) AS cohort_start
    FROM target_raw
    GROUP BY person_id
),
outcome_raw AS (
    {outcome_sql}
),
outcome_first AS (
    SELECT person_id, MIN(cohort_start_date) AS outcome_date
    FROM outcome_raw
    GROUP BY person_id
),
analysis AS (
    SELECT
        ce.person_id,
        ce.cohort_start,
        CASE
            WHEN o.outcome_date IS NOT NULL
                 AND o.outcome_date >= {tar_start_expr}
                 AND o.outcome_date <= {tar_end_expr}
            THEN 1 ELSE 0
        END AS had_outcome,
        CASE
            WHEN o.outcome_date IS NOT NULL
                 AND o.outcome_date >= {tar_start_expr}
                 AND o.outcome_date <= {tar_end_expr}
            THEN EXTRACT(EPOCH FROM (o.outcome_date - ({tar_start_expr}))) / 86400.0
            ELSE EXTRACT(EPOCH FROM ({tar_end_expr} - ({tar_start_expr}))) / 86400.0
        END AS time_days,
        EXTRACT(YEAR FROM ({tar_start_expr})) - p.year_of_birth AS age,
        p.gender_concept_id,
        COALESCE(gc.concept_name, 'Unknown') AS gender_name,
        EXTRACT(YEAR FROM ({tar_start_expr}))::int AS calendar_year
    FROM cohort_entry ce
    JOIN {omop_schema}.observation_period op
        ON ce.person_id = op.person_id
        AND ce.cohort_start BETWEEN op.observation_period_start_date AND op.observation_period_end_date
    JOIN {omop_schema}.person p ON ce.person_id = p.person_id
    LEFT JOIN {omop_schema}.concept gc ON p.gender_concept_id = gc.concept_id
    LEFT JOIN outcome_first o ON ce.person_id = o.person_id
    WHERE {tar_start_expr} < {tar_end_expr}
{clean_filter})
SELECT person_id, had_outcome, time_days, age, gender_concept_id, gender_name, calendar_year
FROM analysis
WHERE time_days > 0
"""
    return sql


def compute_incidence(rows: list[dict], strata: list[str], age_groups: list[dict] | None = None) -> dict:
    """
    Compute incidence rate and proportion from individual-level data.

    rows: list of dicts with keys: had_outcome, time_days, age, gender_name, calendar_year
    strata: list of strata keys to group by
    age_groups: optional list of {min, max, label}
    """
    if not rows:
        return {
            "target_count": 0,
            "outcome_count": 0,
            "person_years": 0,
            "incidence_rate": 0,
            "incidence_proportion": 0,
            "ci_lower": 0,
            "ci_upper": 0,
            "strata": [],
        }

    # Assign age groups
    if age_groups and "age_group" in strata:
        for r in rows:
            r["age_group"] = _classify_age(r.get("age", 0), age_groups)

    # Overall
    overall = _aggregate(rows)

    # By strata
    strata_results = []
    if strata:
        groups = {}
        for r in rows:
            key = tuple(str(r.get(s, "Unknown")) for s in strata)
            groups.setdefault(key, []).append(r)

        for key, group_rows in sorted(groups.items()):
            agg = _aggregate(group_rows)
            agg["strata_values"] = {s: k for s, k in zip(strata, key)}
            strata_results.append(agg)

    overall["strata"] = strata_results
    return overall


def _aggregate(rows: list[dict]) -> dict:
    n = len(rows)
    outcomes = sum(1 for r in rows if r["had_outcome"])
    total_days = sum(r["time_days"] for r in rows)
    person_years = total_days / 365.25

    rate = outcomes / person_years if person_years > 0 else 0
    proportion = outcomes / n if n > 0 else 0

    # Poisson exact CI for rate
    ci_lower, ci_upper = _poisson_ci(outcomes, person_years)

    return {
        "target_count": n,
        "outcome_count": outcomes,
        "person_years": round(person_years, 2),
        "incidence_rate": round(rate, 6),
        "incidence_proportion": round(proportion, 6),
        "ci_lower": round(ci_lower, 6),
        "ci_upper": round(ci_upper, 6),
    }


def _poisson_ci(events: int, person_years: float, alpha: float = 0.05) -> tuple[float, float]:
    """Approximate Poisson confidence interval for incidence rate."""
    if events == 0 or person_years <= 0:
        return 0.0, 0.0

    # Normal approximation for simplicity
    rate = events / person_years
    se = sqrt(events) / person_years
    z = 1.96  # ~95% CI
    return max(0, rate - z * se), rate + z * se


def _classify_age(age: float, age_groups: list[dict]) -> str:
    for ag in age_groups:
        if ag.get("min", 0) <= age <= ag.get("max", 999):
            return ag.get("label", f"{ag.get('min', 0)}-{ag.get('max', 999)}")
    return "Other"
