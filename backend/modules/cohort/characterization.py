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


def run_characterization(conn, criteria: dict, omop_schema: str, top_n: int = _TOP_N) -> dict:
    """
    Run full Table 1 characterization for the given cohort criteria.

    Returns a dict with sections: demographics, domain_prevalence, measurement_stats.
    """
    from psycopg2.extras import RealDictCursor

    cohort_sql = build_cohort_sql(criteria, omop_schema)

    results: dict[str, Any] = {}

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # ── 1. Demographics ──
        results["demographics"] = _query_demographics(cur, cohort_sql, omop_schema)

        # ── 2. Cohort size ──
        cur.execute(f"SELECT COUNT(DISTINCT person_id) AS n FROM ({cohort_sql}) AS _coh")
        results["cohort_size"] = cur.fetchone()["n"]

        # ── 3. Domain prevalence ──
        domain_prev: list[dict] = []
        for domain_name in _CHAR_DOMAINS:
            cfg = DOMAIN_CONFIG.get(domain_name)
            if not cfg:
                continue
            try:
                dp = _query_domain_prevalence(
                    cur, cohort_sql, omop_schema, domain_name, cfg, top_n,
                    results["cohort_size"],
                )
                domain_prev.append(dp)
            except Exception as e:
                logger.warning("Characterization: domain %s failed: %s", domain_name, e)
                conn.rollback()
                domain_prev.append({
                    "domain": domain_name,
                    "patients_with_data": 0,
                    "pct_with_data": 0,
                    "top_concepts": [],
                    "error": str(e),
                })
        results["domain_prevalence"] = domain_prev

        # ── 4. Measurement value stats (top measurements by patient count) ──
        try:
            results["measurement_stats"] = _query_measurement_stats(
                cur, cohort_sql, omop_schema, top_n, results["cohort_size"],
            )
        except Exception as e:
            logger.warning("Characterization: measurement stats failed: %s", e)
            conn.rollback()
            results["measurement_stats"] = []

        # ── 5. Visit type distribution ──
        try:
            results["visit_types"] = _query_visit_types(
                cur, cohort_sql, omop_schema, results["cohort_size"],
            )
        except Exception as e:
            logger.warning("Characterization: visit types failed: %s", e)
            conn.rollback()
            results["visit_types"] = []

        # ── 6. Observation period stats ──
        try:
            results["observation_period"] = _query_observation_period(
                cur, cohort_sql, omop_schema,
            )
        except Exception as e:
            logger.warning("Characterization: obs period failed: %s", e)
            conn.rollback()
            results["observation_period"] = {}

    return results


# ─────────────────────────────────────────────
# Internal query builders
# ─────────────────────────────────────────────

def _query_demographics(cur, cohort_sql: str, schema: str) -> dict:
    """Age, gender, race, ethnicity distributions."""

    # Age statistics
    cur.execute(f"""
        WITH coh AS ({cohort_sql})
        SELECT
            COUNT(*)                                           AS n,
            ROUND(AVG(EXTRACT(YEAR FROM CURRENT_DATE) - p.year_of_birth)::numeric, 1) AS mean_age,
            ROUND(STDDEV(EXTRACT(YEAR FROM CURRENT_DATE) - p.year_of_birth)::numeric, 1) AS std_age,
            MIN(EXTRACT(YEAR FROM CURRENT_DATE) - p.year_of_birth)::int AS min_age,
            MAX(EXTRACT(YEAR FROM CURRENT_DATE) - p.year_of_birth)::int AS max_age,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY EXTRACT(YEAR FROM CURRENT_DATE) - p.year_of_birth)::numeric AS q1_age,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY EXTRACT(YEAR FROM CURRENT_DATE) - p.year_of_birth)::numeric AS median_age,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY EXTRACT(YEAR FROM CURRENT_DATE) - p.year_of_birth)::numeric AS q3_age
        FROM coh
        JOIN {schema}.person p ON coh.person_id = p.person_id
    """)
    age_row = dict(cur.fetchone())
    # Convert Decimals to float
    for k, v in age_row.items():
        if v is not None and not isinstance(v, (int, float, str)):
            age_row[k] = float(v)

    # Age brackets
    cur.execute(f"""
        WITH coh AS ({cohort_sql}),
        ages AS (
            SELECT EXTRACT(YEAR FROM CURRENT_DATE) - p.year_of_birth AS age
            FROM coh
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

    # Gender
    cur.execute(f"""
        WITH coh AS ({cohort_sql})
        SELECT
            COALESCE(c.concept_name, 'Unknown') AS label,
            p.gender_concept_id AS concept_id,
            COUNT(*) AS count
        FROM coh
        JOIN {schema}.person p ON coh.person_id = p.person_id
        LEFT JOIN {schema}.concept c ON p.gender_concept_id = c.concept_id
        GROUP BY p.gender_concept_id, c.concept_name
        ORDER BY count DESC
    """)
    gender = [dict(r) for r in cur.fetchall()]

    # Race
    cur.execute(f"""
        WITH coh AS ({cohort_sql})
        SELECT
            COALESCE(c.concept_name, 'Unknown') AS label,
            p.race_concept_id AS concept_id,
            COUNT(*) AS count
        FROM coh
        JOIN {schema}.person p ON coh.person_id = p.person_id
        LEFT JOIN {schema}.concept c ON p.race_concept_id = c.concept_id
        GROUP BY p.race_concept_id, c.concept_name
        ORDER BY count DESC
    """)
    race = [dict(r) for r in cur.fetchall()]

    # Ethnicity
    cur.execute(f"""
        WITH coh AS ({cohort_sql})
        SELECT
            COALESCE(c.concept_name, 'Unknown') AS label,
            p.ethnicity_concept_id AS concept_id,
            COUNT(*) AS count
        FROM coh
        JOIN {schema}.person p ON coh.person_id = p.person_id
        LEFT JOIN {schema}.concept c ON p.ethnicity_concept_id = c.concept_id
        GROUP BY p.ethnicity_concept_id, c.concept_name
        ORDER BY count DESC
    """)
    ethnicity = [dict(r) for r in cur.fetchall()]

    return {
        "age": age_row,
        "age_groups": age_groups,
        "gender": gender,
        "race": race,
        "ethnicity": ethnicity,
    }


def _query_domain_prevalence(
    cur, cohort_sql: str, schema: str, domain_name: str, cfg: dict,
    top_n: int, cohort_size: int,
) -> dict:
    """For a clinical domain, return % of cohort with data + top concepts."""
    table = f"{schema}.{cfg['table']}"
    pid = cfg["person_id"]
    cid = cfg["concept_id"]

    # Patients with at least one record
    cur.execute(f"""
        WITH coh AS ({cohort_sql})
        SELECT COUNT(DISTINCT t.{pid}) AS n
        FROM coh
        JOIN {table} t ON coh.person_id = t.{pid}
    """)
    n_patients = cur.fetchone()["n"]
    pct = round(100.0 * n_patients / cohort_size, 1) if cohort_size > 0 else 0

    # Top concepts
    cur.execute(f"""
        WITH coh AS ({cohort_sql})
        SELECT
            t.{cid} AS concept_id,
            COALESCE(c.concept_name, 'Unknown') AS concept_name,
            COALESCE(c.concept_code, '') AS concept_code,
            COALESCE(c.vocabulary_id, '') AS vocabulary_id,
            COUNT(DISTINCT t.{pid}) AS n_persons,
            COUNT(*) AS n_records
        FROM coh
        JOIN {table} t ON coh.person_id = t.{pid}
        LEFT JOIN {schema}.concept c ON t.{cid} = c.concept_id
        GROUP BY t.{cid}, c.concept_name, c.concept_code, c.vocabulary_id
        ORDER BY n_persons DESC
        LIMIT {int(top_n)}
    """)
    top_concepts = []
    for row in cur.fetchall():
        r = dict(row)
        r["pct_persons"] = round(100.0 * r["n_persons"] / cohort_size, 1) if cohort_size > 0 else 0
        top_concepts.append(r)

    return {
        "domain": domain_name,
        "patients_with_data": n_patients,
        "pct_with_data": pct,
        "top_concepts": top_concepts,
    }


def _query_measurement_stats(
    cur, cohort_sql: str, schema: str, top_n: int, cohort_size: int,
) -> list[dict]:
    """Top measurements with value statistics (mean, SD, median, range)."""
    mcfg = DOMAIN_CONFIG.get("Measurement")
    if not mcfg:
        return []

    table = f"{schema}.{mcfg['table']}"
    pid = mcfg["person_id"]
    cid = mcfg["concept_id"]

    cur.execute(f"""
        WITH coh AS ({cohort_sql}),
        meas AS (
            SELECT
                t.{cid} AS concept_id,
                t.value_as_number,
                t.unit_source_value,
                t.{pid} AS person_id
            FROM coh
            JOIN {table} t ON coh.person_id = t.{pid}
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
    cur, cohort_sql: str, schema: str, cohort_size: int,
) -> list[dict]:
    """Distribution of visit types in the cohort."""
    vcfg = DOMAIN_CONFIG.get("Visit")
    if not vcfg:
        return []

    table = f"{schema}.{vcfg['table']}"
    pid = vcfg["person_id"]
    cid = vcfg["concept_id"]

    cur.execute(f"""
        WITH coh AS ({cohort_sql})
        SELECT
            t.{cid} AS concept_id,
            COALESCE(c.concept_name, 'Unknown') AS concept_name,
            COUNT(DISTINCT t.{pid}) AS n_persons,
            COUNT(*) AS n_records
        FROM coh
        JOIN {table} t ON coh.person_id = t.{pid}
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


def _query_observation_period(cur, cohort_sql: str, schema: str) -> dict:
    """Observation period stats for the cohort."""
    cur.execute(f"""
        WITH coh AS ({cohort_sql}),
        obs AS (
            SELECT
                op.person_id,
                op.observation_period_start_date,
                op.observation_period_end_date,
                (op.observation_period_end_date - op.observation_period_start_date) AS days
            FROM coh
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
