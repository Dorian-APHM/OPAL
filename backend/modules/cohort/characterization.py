"""
Cohort Characterization Engine — "Table 1" generation.

Given a cohort definition (criteria JSON), runs a battery of SQL queries against
the OMOP CDM to produce a structured characterization report:
  - Demographics: age, gender, race, ethnicity distributions
  - Clinical prevalence: top conditions, drugs, procedures, measurements, etc.
  - Measurement values: mean/SD/median for top lab results
"""
import logging
from typing import Any

from config import DOMAIN_CONFIG
from modules.cohort.sql_builder import build_cohort_sql

logger = logging.getLogger(__name__)

# Domains to characterize (skip Visit/Death for top-concept prevalence — less useful)
_CHAR_DOMAINS = ["Condition", "Drug", "Procedure", "Measurement", "Observation", "Device"]

# How many top concepts per domain
_TOP_N = 25


def run_characterization(
    conn, criteria: dict, omop_schema: str, top_n: int = _TOP_N,
    visit_level: bool = False,
    progress_callback=None,
) -> dict:
    """
    Run full Table 1 characterization for the given cohort criteria.

    Returns a dict with sections: demographics, domain_prevalence, measurement_stats.

    When visit_level=True and the cohort uses sameVisit, clinical domain queries
    are restricted to the qualifying visit only (not all patient data).
    Demographics remain patient-level.
    """
    from psycopg2.extras import RealDictCursor

    # Check if visit-level mode is applicable
    has_same_visit = bool(criteria.get("inclusion", {}).get("sameVisit", False))
    effective_visit_level = visit_level and has_same_visit

    cohort_sql = build_cohort_sql(
        criteria, omop_schema, include_visit_id=effective_visit_level,
    )

    results: dict[str, Any] = {}
    results["visit_level"] = effective_visit_level

    # Total steps: cohort + demographics + 6 domains + measurements + visits + visit_duration + obs_period = 12
    total_steps = 2 + len(_CHAR_DOMAINS) + 4  # cohort+demo, 6 domains, meas+visits+visit_dur+obs
    completed_steps = 0

    def _report(step_label: str):
        nonlocal completed_steps
        completed_steps += 1
        if progress_callback:
            progress_callback(completed_steps, total_steps, step_label)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # ── 0. Materialize cohort into a temp table (executed ONCE) ──
        cur.execute("DROP TABLE IF EXISTS _coh_char")
        if effective_visit_level:
            cur.execute(f"""
                CREATE TEMP TABLE _coh_char AS
                SELECT DISTINCT person_id, visit_occurrence_id
                FROM ({cohort_sql}) AS _coh_src
            """)
            cur.execute("CREATE INDEX ON _coh_char (person_id)")
            cur.execute("CREATE INDEX ON _coh_char (person_id, visit_occurrence_id)")
        else:
            cur.execute(f"""
                CREATE TEMP TABLE _coh_char AS
                SELECT DISTINCT person_id FROM ({cohort_sql}) AS _coh_src
            """)
            cur.execute("CREATE INDEX ON _coh_char (person_id)")
        _report("Cohort materialized")

        # ── 1. Demographics ──
        results["demographics"] = _query_demographics(cur, omop_schema)

        # ── 2. Cohort size ──
        cur.execute("SELECT COUNT(DISTINCT person_id) AS n FROM _coh_char")
        results["cohort_size"] = cur.fetchone()["n"]
        _report("Demographics")

        # ── 3. Domain prevalence ──
        domain_prev: list[dict] = []
        for domain_name in _CHAR_DOMAINS:
            cfg = DOMAIN_CONFIG.get(domain_name)
            if not cfg:
                _report(domain_name)
                continue
            try:
                cur.execute("SAVEPOINT sp_domain")
                dp = _query_domain_prevalence(
                    cur, omop_schema, domain_name, cfg, top_n,
                    results["cohort_size"],
                    visit_level=effective_visit_level,
                )
                cur.execute("RELEASE SAVEPOINT sp_domain")
                domain_prev.append(dp)
            except Exception as e:
                logger.warning("Characterization: domain %s failed: %s", domain_name, e)
                cur.execute("ROLLBACK TO SAVEPOINT sp_domain")
                domain_prev.append({
                    "domain": domain_name,
                    "patients_with_data": 0,
                    "pct_with_data": 0,
                    "top_concepts": [],
                    "error": str(e),
                })
            _report(domain_name)
        results["domain_prevalence"] = domain_prev

        # ── 4. Measurement value stats (top measurements by patient count) ──
        try:
            cur.execute("SAVEPOINT sp_meas")
            results["measurement_stats"] = _query_measurement_stats(
                cur, omop_schema, top_n, results["cohort_size"],
                visit_level=effective_visit_level,
            )
            cur.execute("RELEASE SAVEPOINT sp_meas")
        except Exception as e:
            logger.warning("Characterization: measurement stats failed: %s", e)
            cur.execute("ROLLBACK TO SAVEPOINT sp_meas")
            results["measurement_stats"] = []
        _report("Measurement stats")

        # ── 5. Visit type distribution ──
        try:
            cur.execute("SAVEPOINT sp_visit")
            results["visit_types"] = _query_visit_types(
                cur, omop_schema, results["cohort_size"],
                visit_level=effective_visit_level,
            )
            cur.execute("RELEASE SAVEPOINT sp_visit")
        except Exception as e:
            logger.warning("Characterization: visit types failed: %s", e)
            cur.execute("ROLLBACK TO SAVEPOINT sp_visit")
            results["visit_types"] = []
        _report("Visit types")

        # ── 5b. Visit duration stats ──
        try:
            cur.execute("SAVEPOINT sp_vdur")
            results["visit_duration"] = _query_visit_duration(
                cur, omop_schema,
                visit_level=effective_visit_level,
            )
            cur.execute("RELEASE SAVEPOINT sp_vdur")
        except Exception as e:
            logger.warning("Characterization: visit duration failed: %s", e)
            cur.execute("ROLLBACK TO SAVEPOINT sp_vdur")
            results["visit_duration"] = {}
        _report("Visit duration")

        # ── 6. Observation period stats ──
        try:
            cur.execute("SAVEPOINT sp_obs")
            results["observation_period"] = _query_observation_period(
                cur, omop_schema,
            )
            cur.execute("RELEASE SAVEPOINT sp_obs")
        except Exception as e:
            logger.warning("Characterization: obs period failed: %s", e)
            cur.execute("ROLLBACK TO SAVEPOINT sp_obs")
            results["observation_period"] = {}
        _report("Observation period")

        # Cleanup temp table
        cur.execute("DROP TABLE IF EXISTS _coh_char")

    return results


# ─────────────────────────────────────────────
# Internal query builders
# ─────────────────────────────────────────────

def _query_demographics(cur, schema: str) -> dict:
    """Age, gender, race, ethnicity distributions."""

    # Age statistics + age brackets in a single query
    cur.execute(f"""
        WITH ages AS (
            SELECT EXTRACT(YEAR FROM CURRENT_DATE) - p.year_of_birth AS age
            FROM _coh_char coh
            JOIN {schema}.person p ON coh.person_id = p.person_id
        )
        SELECT
            COUNT(*)                                           AS n,
            ROUND(AVG(age)::numeric, 1)                        AS mean_age,
            ROUND(STDDEV(age)::numeric, 1)                     AS std_age,
            MIN(age)::int                                      AS min_age,
            MAX(age)::int                                      AS max_age,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY age)::numeric AS q1_age,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY age)::numeric AS median_age,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY age)::numeric AS q3_age
        FROM ages
    """)
    age_row = dict(cur.fetchone())
    for k, v in age_row.items():
        if v is not None and not isinstance(v, (int, float, str)):
            age_row[k] = float(v)

    # Age brackets
    cur.execute(f"""
        WITH ages AS (
            SELECT EXTRACT(YEAR FROM CURRENT_DATE) - p.year_of_birth AS age
            FROM _coh_char coh
            JOIN {schema}.person p ON coh.person_id = p.person_id
        )
        SELECT
            CASE
                WHEN age < 18 THEN '0-17'
                WHEN age < 30 THEN '18-29'
                WHEN age < 40 THEN '30-39'
                WHEN age < 50 THEN '40-49'
                WHEN age < 60 THEN '50-59'
                WHEN age < 70 THEN '60-69'
                WHEN age < 80 THEN '70-79'
                ELSE '80+'
            END AS age_group,
            COUNT(*) AS count
        FROM ages
        GROUP BY 1
        ORDER BY MIN(age)
    """)
    age_groups = [dict(r) for r in cur.fetchall()]

    # Gender, race, ethnicity in a single query
    cur.execute(f"""
        SELECT
            COALESCE(cg.concept_name, 'Unknown') AS gender_label,
            p.gender_concept_id,
            COALESCE(cr.concept_name, 'Unknown') AS race_label,
            p.race_concept_id,
            COALESCE(ce.concept_name, 'Unknown') AS ethnicity_label,
            p.ethnicity_concept_id,
            COUNT(*) AS count
        FROM _coh_char coh
        JOIN {schema}.person p ON coh.person_id = p.person_id
        LEFT JOIN {schema}.concept cg ON p.gender_concept_id = cg.concept_id
        LEFT JOIN {schema}.concept cr ON p.race_concept_id = cr.concept_id
        LEFT JOIN {schema}.concept ce ON p.ethnicity_concept_id = ce.concept_id
        GROUP BY p.gender_concept_id, cg.concept_name,
                 p.race_concept_id, cr.concept_name,
                 p.ethnicity_concept_id, ce.concept_name
    """)
    rows = [dict(r) for r in cur.fetchall()]

    # Aggregate gender, race, ethnicity from the combined rows
    gender_map: dict[tuple, int] = {}
    race_map: dict[tuple, int] = {}
    ethnicity_map: dict[tuple, int] = {}
    for r in rows:
        gk = (r["gender_label"], r["gender_concept_id"])
        gender_map[gk] = gender_map.get(gk, 0) + r["count"]
        rk = (r["race_label"], r["race_concept_id"])
        race_map[rk] = race_map.get(rk, 0) + r["count"]
        ek = (r["ethnicity_label"], r["ethnicity_concept_id"])
        ethnicity_map[ek] = ethnicity_map.get(ek, 0) + r["count"]

    gender = sorted(
        [{"label": k[0], "concept_id": k[1], "count": v} for k, v in gender_map.items()],
        key=lambda x: x["count"], reverse=True,
    )
    race = sorted(
        [{"label": k[0], "concept_id": k[1], "count": v} for k, v in race_map.items()],
        key=lambda x: x["count"], reverse=True,
    )
    ethnicity = sorted(
        [{"label": k[0], "concept_id": k[1], "count": v} for k, v in ethnicity_map.items()],
        key=lambda x: x["count"], reverse=True,
    )

    return {
        "age": age_row,
        "age_groups": age_groups,
        "gender": gender,
        "race": race,
        "ethnicity": ethnicity,
    }


def _query_domain_prevalence(
    cur, schema: str, domain_name: str, cfg: dict,
    top_n: int, cohort_size: int,
    visit_level: bool = False,
) -> dict:
    """For a clinical domain, return % of cohort with data + top concepts."""
    table = f"{schema}.{cfg['table']}"
    pid = cfg["person_id"]
    cid = cfg["concept_id"]

    # Visit-level: restrict to records from the qualifying visit only
    visit_join = (
        f"JOIN {table} t ON coh.person_id = t.{pid} AND coh.visit_occurrence_id = t.visit_occurrence_id"
        if visit_level else
        f"JOIN {table} t ON coh.person_id = t.{pid}"
    )

    # Single query: top concepts + total patients with data via window function
    cur.execute(f"""
        WITH domain_data AS (
            SELECT
                t.{cid} AS concept_id,
                t.{pid} AS person_id
            FROM _coh_char coh
            {visit_join}
        ),
        total AS (
            SELECT COUNT(DISTINCT person_id) AS n FROM domain_data
        ),
        top AS (
            SELECT
                concept_id,
                COUNT(DISTINCT person_id) AS n_persons,
                COUNT(*) AS n_records
            FROM domain_data
            GROUP BY concept_id
            ORDER BY n_persons DESC
            LIMIT {int(top_n)}
        )
        SELECT
            total.n AS total_patients_with_data,
            top.concept_id,
            COALESCE(c.concept_name, 'Unknown') AS concept_name,
            COALESCE(c.concept_code, '') AS concept_code,
            COALESCE(c.vocabulary_id, '') AS vocabulary_id,
            top.n_persons,
            top.n_records
        FROM top
        CROSS JOIN total
        LEFT JOIN {schema}.concept c ON top.concept_id = c.concept_id
        ORDER BY top.n_persons DESC
    """)
    rows = cur.fetchall()

    n_patients = rows[0]["total_patients_with_data"] if rows else 0
    pct = round(100.0 * n_patients / cohort_size, 1) if cohort_size > 0 else 0

    top_concepts = []
    for row in rows:
        r = dict(row)
        r["pct_persons"] = round(100.0 * r["n_persons"] / cohort_size, 1) if cohort_size > 0 else 0
        del r["total_patients_with_data"]
        top_concepts.append(r)

    return {
        "domain": domain_name,
        "patients_with_data": n_patients,
        "pct_with_data": pct,
        "top_concepts": top_concepts,
    }


def _query_measurement_stats(
    cur, schema: str, top_n: int, cohort_size: int,
    visit_level: bool = False,
) -> list[dict]:
    """Top measurements with value statistics (mean, SD, median, range)."""
    mcfg = DOMAIN_CONFIG.get("Measurement")
    if not mcfg:
        return []

    table = f"{schema}.{mcfg['table']}"
    pid = mcfg["person_id"]
    cid = mcfg["concept_id"]

    visit_join = (
        f"JOIN {table} t ON coh.person_id = t.{pid} AND coh.visit_occurrence_id = t.visit_occurrence_id"
        if visit_level else
        f"JOIN {table} t ON coh.person_id = t.{pid}"
    )

    cur.execute(f"""
        WITH meas AS (
            SELECT
                t.{cid} AS concept_id,
                t.value_as_number,
                t.unit_source_value,
                t.{pid} AS person_id
            FROM _coh_char coh
            {visit_join}
            WHERE t.value_as_number IS NOT NULL
        ),
        ranked AS (
            SELECT concept_id, COUNT(DISTINCT person_id) AS n_persons
            FROM meas
            GROUP BY concept_id
            ORDER BY n_persons DESC
            LIMIT {int(top_n)}
        )
        SELECT
            r.concept_id,
            COALESCE(c.concept_name, 'Unknown') AS concept_name,
            COALESCE(c.concept_code, '') AS concept_code,
            r.n_persons,
            ROUND(AVG(m.value_as_number)::numeric, 2) AS mean_value,
            ROUND(STDDEV(m.value_as_number)::numeric, 2) AS std_value,
            ROUND((PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY m.value_as_number))::numeric, 2) AS median_value,
            MIN(m.value_as_number) AS min_value,
            MAX(m.value_as_number) AS max_value,
            MODE() WITHIN GROUP (ORDER BY COALESCE(m.unit_source_value, '')) AS unit
        FROM ranked r
        JOIN meas m ON r.concept_id = m.concept_id
        LEFT JOIN {schema}.concept c ON r.concept_id = c.concept_id
        GROUP BY r.concept_id, r.n_persons, c.concept_name, c.concept_code
        ORDER BY r.n_persons DESC
    """)
    results = []
    for row in cur.fetchall():
        r = dict(row)
        r["pct_persons"] = round(100.0 * r["n_persons"] / cohort_size, 1) if cohort_size > 0 else 0
        # Convert Decimal to float
        for k, v in r.items():
            if v is not None and not isinstance(v, (int, float, str)):
                try:
                    r[k] = float(v)
                except (TypeError, ValueError):
                    pass
        results.append(r)

    return results


def _query_visit_types(
    cur, schema: str, cohort_size: int,
    visit_level: bool = False,
) -> list[dict]:
    """Distribution of visit types in the cohort."""
    vcfg = DOMAIN_CONFIG.get("Visit")
    if not vcfg:
        return []

    table = f"{schema}.{vcfg['table']}"
    pid = vcfg["person_id"]
    cid = vcfg["concept_id"]

    visit_join = (
        f"JOIN {table} t ON coh.person_id = t.{pid} AND coh.visit_occurrence_id = t.visit_occurrence_id"
        if visit_level else
        f"JOIN {table} t ON coh.person_id = t.{pid}"
    )

    cur.execute(f"""
        SELECT
            t.{cid} AS concept_id,
            COALESCE(c.concept_name, 'Unknown') AS concept_name,
            COUNT(DISTINCT t.{pid}) AS n_persons,
            COUNT(*) AS n_records
        FROM _coh_char coh
        {visit_join}
        LEFT JOIN {schema}.concept c ON t.{cid} = c.concept_id
        GROUP BY t.{cid}, c.concept_name
        ORDER BY n_persons DESC
        LIMIT 15
    """)
    results = []
    for row in cur.fetchall():
        r = dict(row)
        r["pct_persons"] = round(100.0 * r["n_persons"] / cohort_size, 1) if cohort_size > 0 else 0
        results.append(r)
    return results


def _query_observation_period(cur, schema: str) -> dict:
    """Observation period stats for the cohort."""
    cur.execute(f"""
        WITH obs AS (
            SELECT
                op.person_id,
                op.observation_period_start_date,
                op.observation_period_end_date,
                (op.observation_period_end_date - op.observation_period_start_date) AS days
            FROM _coh_char coh
            JOIN {schema}.observation_period op ON coh.person_id = op.person_id
        )
        SELECT
            COUNT(*) AS n_periods,
            COUNT(DISTINCT person_id) AS n_persons,
            ROUND(AVG(days)::numeric, 0) AS mean_days,
            ROUND(STDDEV(days)::numeric, 0) AS std_days,
            MIN(days) AS min_days,
            MAX(days) AS max_days,
            ROUND((PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY days))::numeric, 0) AS median_days,
            MIN(observation_period_start_date) AS earliest_start,
            MAX(observation_period_end_date) AS latest_end
        FROM obs
    """)
    row = dict(cur.fetchone())
    # Convert types
    for k, v in row.items():
        if v is not None and hasattr(v, 'isoformat'):
            row[k] = v.isoformat()
        elif v is not None and not isinstance(v, (int, float, str)):
            try:
                row[k] = float(v)
            except (TypeError, ValueError):
                row[k] = str(v)
    return row


def _query_visit_duration(cur, schema: str, visit_level: bool = False) -> dict:
    """Average visit duration in days, overall and by visit type."""
    visit_join = (
        f"JOIN {schema}.visit_occurrence v ON coh.person_id = v.person_id AND coh.visit_occurrence_id = v.visit_occurrence_id"
        if visit_level else
        f"JOIN {schema}.visit_occurrence v ON coh.person_id = v.person_id"
    )

    cur.execute(f"""
        WITH durations AS (
            SELECT
                v.visit_concept_id,
                COALESCE(c.concept_name, 'Unknown') AS visit_type,
                GREATEST(v.visit_end_date - v.visit_start_date, 0) AS days
            FROM _coh_char coh
            {visit_join}
            LEFT JOIN {schema}.concept c ON v.visit_concept_id = c.concept_id
            WHERE v.visit_start_date IS NOT NULL AND v.visit_end_date IS NOT NULL
        )
        SELECT
            COUNT(*) AS n_visits,
            ROUND(AVG(days)::numeric, 1) AS mean_days,
            ROUND(STDDEV(days)::numeric, 1) AS std_days,
            MIN(days) AS min_days,
            MAX(days) AS max_days,
            ROUND((PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY days))::numeric, 1) AS median_days
        FROM durations
    """)
    overall = dict(cur.fetchone())
    for k, v in overall.items():
        if v is not None and not isinstance(v, (int, float, str)):
            try:
                overall[k] = float(v)
            except (TypeError, ValueError):
                overall[k] = str(v)

    # By visit type (top 10)
    cur.execute(f"""
        WITH durations AS (
            SELECT
                v.visit_concept_id,
                COALESCE(c.concept_name, 'Unknown') AS visit_type,
                GREATEST(v.visit_end_date - v.visit_start_date, 0) AS days
            FROM _coh_char coh
            {visit_join}
            LEFT JOIN {schema}.concept c ON v.visit_concept_id = c.concept_id
            WHERE v.visit_start_date IS NOT NULL AND v.visit_end_date IS NOT NULL
        )
        SELECT
            visit_type,
            COUNT(*) AS n_visits,
            ROUND(AVG(days)::numeric, 1) AS mean_days,
            ROUND(STDDEV(days)::numeric, 1) AS std_days,
            ROUND((PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY days))::numeric, 1) AS median_days
        FROM durations
        GROUP BY visit_type
        ORDER BY n_visits DESC
        LIMIT 10
    """)
    by_type = []
    for row in cur.fetchall():
        r = dict(row)
        for k, v in r.items():
            if v is not None and not isinstance(v, (int, float, str)):
                try:
                    r[k] = float(v)
                except (TypeError, ValueError):
                    pass
        by_type.append(r)

    overall["by_type"] = by_type
    return overall
