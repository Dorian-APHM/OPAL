"""
Observation Period domain analysis — ported from achilles_like/analysis.py.
All 6 sub-analyses preserved exactly.
"""
from psycopg2 import sql as psysql
from psycopg2.extras import DictCursor

from config import DEFAULT_MAX_OBSERVATION_MONTHS
from utils.sql_safety import safe_identifier


def run_observation_period_analysis(conn, omop_schema: str = "omop_cdm",
                                     cap_months: int | None = None) -> dict:
    """
    ObservationPeriod analyses:
    1. Age at first observation
    2. Age by gender (boxplot quantiles)
    3. Observation length in months (capped)
    4. Duration by gender (boxplot quantiles)
    5. Cumulative observation
    6. Continuous observation by year

    P13 fix: queries are grouped to share the same CTE `per` and reduce
    the number of full scans on observation_period from 6 down to 4.
    (No temp tables — CDM connection is read-only.)
    """
    if cap_months is None:
        cap_months = DEFAULT_MAX_OBSERVATION_MONTHS

    # observation_period and person are both clinical; concept is vocabulary —
    # they may live in different schemas when per-category schemas are configured.
    clinical_schema = omop_schema.schema_for("person") if hasattr(omop_schema, "schema_for") else safe_identifier(omop_schema)
    concept_schema = omop_schema.schema_for("concept") if hasattr(omop_schema, "schema_for") else safe_identifier(omop_schema)
    _s = psysql.Identifier(safe_identifier(clinical_schema))
    _sv = psysql.Identifier(safe_identifier(concept_schema))
    _obs = psysql.Identifier("observation_period")
    _person = psysql.Identifier("person")
    _concept = psysql.Identifier("concept")

    obs_table_str = f"{clinical_schema}.observation_period"

    res = {
        "domain": "ObservationPeriod",
        "table": obs_table_str,
        "achilles_like": {},
        "mapping": {},
    }

    # Helper: build exact birth date using day_of_birth/month_of_birth when available,
    # fallback to July 1st of year_of_birth otherwise.
    birth_date_expr = """
        MAKE_DATE(
            p.year_of_birth,
            COALESCE(NULLIF(p.month_of_birth, 0), 7),
            COALESCE(NULLIF(p.day_of_birth, 0), 1)
        )
    """

    # Shared CTE fragment: per-person min/max observation dates
    per_cte = psysql.SQL("""
        per AS (
            SELECT
                person_id,
                MIN(observation_period_start_date) AS obs_start,
                MAX(observation_period_end_date) AS obs_end
            FROM {schema}.{obs}
            GROUP BY person_id
        )
    """).format(schema=_s, obs=_obs)

    with conn.cursor(cursor_factory=DictCursor) as cur:
        # 1) Age at First Observation (integer years for histogram)
        cur.execute(psysql.SQL("""
            WITH {per_cte}
            SELECT
                (EXTRACT(YEAR FROM AGE(per.obs_start, {birth_date})))::int AS age,
                COUNT(*) AS n
            FROM per
            JOIN {schema}.{person} p ON p.person_id = per.person_id
            WHERE per.obs_start IS NOT NULL
              AND p.year_of_birth IS NOT NULL
              AND EXTRACT(YEAR FROM AGE(per.obs_start, {birth_date})) BETWEEN 0 AND 120
            GROUP BY 1
            ORDER BY age
        """).format(
            per_cte=per_cte, schema=_s, person=_person,
            birth_date=psysql.SQL(birth_date_expr),
        ))
        ages, counts = [], []
        for r in cur.fetchall():
            ages.append(int(r["age"]))
            counts.append(int(r["n"]))
        res["achilles_like"]["age_at_first_observation"] = {"age": ages, "count": counts}

        # 2) Age by Gender (exact decimal age for boxplot quantiles)
        cur.execute(psysql.SQL("""
            WITH {per_cte},
            ages AS (
                SELECT
                    p.person_id,
                    p.gender_concept_id,
                    (per.obs_start - {birth_date})::numeric / 365.25 AS age
                FROM per
                JOIN {schema}.{person} p ON p.person_id = per.person_id
                WHERE per.obs_start IS NOT NULL
                  AND p.year_of_birth IS NOT NULL
                  AND (per.obs_start - {birth_date})::numeric / 365.25 BETWEEN 0 AND 120
            )
            SELECT
                a.gender_concept_id,
                COALESCE(c.concept_name, 'UNKNOWN') AS gender_name,
                COUNT(*) AS n,
                AVG(a.age) AS mean_age,
                PERCENTILE_CONT(0.1) WITHIN GROUP (ORDER BY a.age) AS p10,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY a.age) AS p25,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY a.age) AS median_age,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY a.age) AS p75,
                PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY a.age) AS p90
            FROM ages a
            LEFT JOIN {vschema}.{concept} c ON c.concept_id = a.gender_concept_id
            GROUP BY a.gender_concept_id, COALESCE(c.concept_name, 'UNKNOWN')
            ORDER BY n DESC
        """).format(
            per_cte=per_cte, schema=_s, vschema=_sv, person=_person, concept=_concept,
            birth_date=psysql.SQL(birth_date_expr),
        ))
        rows = []
        for r in cur.fetchall():
            rows.append({
                "gender_concept_id": str(r["gender_concept_id"]) if r["gender_concept_id"] is not None else "",
                "gender_name": r["gender_name"],
                "n": int(r["n"]),
                "mean_age": float(r["mean_age"]) if r["mean_age"] is not None else None,
                "p10": float(r["p10"]) if r["p10"] is not None else None,
                "p25": float(r["p25"]) if r["p25"] is not None else None,
                "median_age": float(r["median_age"]) if r["median_age"] is not None else None,
                "p75": float(r["p75"]) if r["p75"] is not None else None,
                "p90": float(r["p90"]) if r["p90"] is not None else None,
            })
        res["achilles_like"]["age_by_gender"] = {"rows": rows}

        # 3) Observation Length (months, capped)
        cur.execute(psysql.SQL("""
            WITH {per_cte},
            per2 AS (
                SELECT
                    person_id,
                    GREATEST(0, (DATE_PART('year', AGE(obs_end, obs_start))*12
                               + DATE_PART('month', AGE(obs_end, obs_start))))::int AS months
                FROM per
                WHERE obs_start IS NOT NULL AND obs_end IS NOT NULL AND obs_end >= obs_start
            ),
            b AS (
                SELECT CASE WHEN months > %s THEN %s ELSE months END AS m
                FROM per2
            )
            SELECT m AS months, COUNT(*) AS n
            FROM b
            GROUP BY m
            ORDER BY m
        """).format(per_cte=per_cte), (cap_months, cap_months))
        months, n_persons = [], []
        for r in cur.fetchall():
            months.append(int(r["months"]))
            n_persons.append(int(r["n"]))
        res["achilles_like"]["observation_length_months"] = {
            "months": months,
            "n_persons": n_persons,
            "cap_months": cap_months,
        }

        # 4) Duration by Gender (quantiles for boxplot)
        cur.execute(psysql.SQL("""
            WITH {per_cte},
            per2 AS (
                SELECT
                    per.person_id,
                    GREATEST(0, (DATE_PART('year', AGE(per.obs_end, per.obs_start))*12
                               + DATE_PART('month', AGE(per.obs_end, per.obs_start))))::numeric AS months
                FROM per
                WHERE per.obs_start IS NOT NULL
                  AND per.obs_end IS NOT NULL
                  AND per.obs_end >= per.obs_start
            )
            SELECT
                p.gender_concept_id,
                COALESCE(c.concept_name, 'UNKNOWN') AS gender_name,
                COUNT(*) AS n,
                AVG(per2.months) AS mean_months,
                PERCENTILE_CONT(0.1) WITHIN GROUP (ORDER BY per2.months) AS p10,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY per2.months) AS p25,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY per2.months) AS median_months,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY per2.months) AS p75,
                PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY per2.months) AS p90
            FROM per2
            JOIN {schema}.{person} p ON p.person_id = per2.person_id
            LEFT JOIN {vschema}.{concept} c ON c.concept_id = p.gender_concept_id
            GROUP BY p.gender_concept_id, COALESCE(c.concept_name, 'UNKNOWN')
            ORDER BY n DESC
        """).format(per_cte=per_cte, schema=_s, vschema=_sv, person=_person, concept=_concept))
        rows = []
        for r in cur.fetchall():
            rows.append({
                "gender_concept_id": str(r["gender_concept_id"]) if r["gender_concept_id"] is not None else "",
                "gender_name": r["gender_name"],
                "n": int(r["n"]),
                "mean_months": float(r["mean_months"]) if r["mean_months"] is not None else None,
                "p10": float(r["p10"]) if r["p10"] is not None else None,
                "p25": float(r["p25"]) if r["p25"] is not None else None,
                "median_months": float(r["median_months"]) if r["median_months"] is not None else None,
                "p75": float(r["p75"]) if r["p75"] is not None else None,
                "p90": float(r["p90"]) if r["p90"] is not None else None,
            })
        res["achilles_like"]["duration_by_gender"] = {"rows": rows}

        # 5) Cumulative Observation (P11 fix: window function instead of correlated subquery)
        cur.execute(psysql.SQL("""
            WITH {per_cte},
            per2 AS (
                SELECT
                    LEAST(GREATEST(0, (DATE_PART('year', AGE(obs_end, obs_start))*12
                               + DATE_PART('month', AGE(obs_end, obs_start))))::int, %s) AS months
                FROM per
                WHERE obs_start IS NOT NULL AND obs_end IS NOT NULL AND obs_end >= obs_start
            ),
            hist AS (
                SELECT months AS m, COUNT(*) AS n FROM per2 GROUP BY months
            ),
            cum AS (
                SELECT m,
                       SUM(n) OVER (ORDER BY m DESC) AS n_ge,
                       SUM(n) OVER () AS n_total
                FROM hist
            )
            SELECT m AS thr, ROUND(n_ge::numeric / n_total * 100.0, 2) AS pct
            FROM cum
            ORDER BY m
        """).format(per_cte=per_cte), (cap_months,))
        thr, pct = [], []
        for r in cur.fetchall():
            thr.append(int(r["thr"]))
            pct.append(float(r["pct"]) if r["pct"] is not None else 0.0)
        res["achilles_like"]["cumulative_observation"] = {"months_threshold": thr, "pct_persons": pct}

        # 6) Continuous Observation by Year
        cur.execute(psysql.SQL("""
            WITH {per_cte},
            years AS (
                SELECT generate_series(
                    (SELECT MIN(EXTRACT(YEAR FROM obs_start))::int FROM per WHERE obs_start IS NOT NULL),
                    (SELECT MAX(EXTRACT(YEAR FROM obs_end))::int FROM per WHERE obs_end IS NOT NULL)
                ) AS y
            )
            SELECT y.y AS year, COUNT(*) AS n_persons
            FROM years y
            JOIN per ON per.obs_start <= MAKE_DATE(y.y::int, 1, 1)
                    AND per.obs_end >= MAKE_DATE(y.y::int, 12, 31)
            GROUP BY y.y
            ORDER BY y.y
        """).format(per_cte=per_cte))
        yrs, nps = [], []
        for r in cur.fetchall():
            yrs.append(int(r["year"]))
            nps.append(int(r["n_persons"]))
        res["achilles_like"]["continuous_observation_by_year"] = {"year": yrs, "n_persons": nps}

    return res
