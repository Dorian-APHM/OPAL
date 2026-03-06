"""
Observation Period domain analysis — ported from achilles_like/analysis.py.
All 6 sub-analyses preserved exactly.
"""
from psycopg2.extras import DictCursor

from config import DEFAULT_MAX_OBSERVATION_MONTHS


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
    """
    if cap_months is None:
        cap_months = DEFAULT_MAX_OBSERVATION_MONTHS

    obs_table = f"{omop_schema}.observation_period"
    person_table = f"{omop_schema}.person"
    concept_table = f"{omop_schema}.concept"

    res = {
        "domain": "ObservationPeriod",
        "table": obs_table,
        "achilles_like": {},
        "mapping": {},
    }

    with conn.cursor(cursor_factory=DictCursor) as cur:
        # 1) Age at First Observation
        cur.execute(f"""
            WITH per AS (
                SELECT person_id, MIN(observation_period_start_date) AS obs_start
                FROM {obs_table}
                GROUP BY person_id
            )
            SELECT
                (EXTRACT(YEAR FROM AGE(per.obs_start, MAKE_DATE(p.year_of_birth, 7, 1))))::int AS age,
                COUNT(*) AS n
            FROM per
            JOIN {person_table} p ON p.person_id = per.person_id
            WHERE per.obs_start IS NOT NULL
              AND p.year_of_birth IS NOT NULL
              AND EXTRACT(YEAR FROM AGE(per.obs_start, MAKE_DATE(p.year_of_birth, 7, 1))) BETWEEN 0 AND 120
            GROUP BY 1
            ORDER BY age
        """)
        ages, counts = [], []
        for r in cur.fetchall():
            ages.append(int(r["age"]))
            counts.append(int(r["n"]))
        res["achilles_like"]["age_at_first_observation"] = {"age": ages, "count": counts}

        # 2) Age by Gender (quantiles for boxplot)
        cur.execute(f"""
            WITH per AS (
                SELECT person_id, MIN(observation_period_start_date) AS obs_start
                FROM {obs_table}
                GROUP BY person_id
            ),
            ages AS (
                SELECT
                    p.person_id,
                    p.gender_concept_id,
                    EXTRACT(YEAR FROM AGE(per.obs_start, MAKE_DATE(p.year_of_birth, 7, 1)))::numeric AS age
                FROM per
                JOIN {person_table} p ON p.person_id = per.person_id
                WHERE per.obs_start IS NOT NULL
                  AND p.year_of_birth IS NOT NULL
                  AND EXTRACT(YEAR FROM AGE(per.obs_start, MAKE_DATE(p.year_of_birth, 7, 1))) BETWEEN 0 AND 120
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
            LEFT JOIN {concept_table} c ON c.concept_id = a.gender_concept_id
            GROUP BY a.gender_concept_id, COALESCE(c.concept_name, 'UNKNOWN')
            ORDER BY n DESC
        """)
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
        cur.execute(f"""
            WITH per AS (
                SELECT
                    person_id,
                    MIN(observation_period_start_date) AS obs_start,
                    MAX(observation_period_end_date) AS obs_end
                FROM {obs_table}
                GROUP BY person_id
            ),
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
        """, (cap_months, cap_months))
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
        cur.execute(f"""
            WITH per AS (
                SELECT
                    op.person_id,
                    MIN(op.observation_period_start_date) AS obs_start,
                    MAX(op.observation_period_end_date) AS obs_end
                FROM {obs_table} op
                WHERE op.person_id IS NOT NULL
                GROUP BY op.person_id
            ),
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
            JOIN {person_table} p ON p.person_id = per2.person_id
            LEFT JOIN {concept_table} c ON c.concept_id = p.gender_concept_id
            GROUP BY p.gender_concept_id, COALESCE(c.concept_name, 'UNKNOWN')
            ORDER BY n DESC
        """)
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

        # 5) Cumulative Observation
        cur.execute(f"""
            WITH per AS (
                SELECT
                    person_id,
                    MIN(observation_period_start_date) AS obs_start,
                    MAX(observation_period_end_date) AS obs_end
                FROM {obs_table}
                GROUP BY person_id
            ),
            per2 AS (
                SELECT
                    person_id,
                    GREATEST(0, (DATE_PART('year', AGE(obs_end, obs_start))*12
                               + DATE_PART('month', AGE(obs_end, obs_start))))::int AS months
                FROM per
                WHERE obs_start IS NOT NULL AND obs_end IS NOT NULL AND obs_end >= obs_start
            ),
            tot AS (SELECT COUNT(*)::numeric AS n_total FROM per2),
            s AS (SELECT generate_series(0, %s) AS thr),
            agg AS (
                SELECT s.thr, (SELECT COUNT(*)::numeric FROM per2 WHERE months >= s.thr) AS n_ge
                FROM s
            )
            SELECT thr, (n_ge / (SELECT n_total FROM tot) * 100.0) AS pct
            FROM agg
            ORDER BY thr
        """, (cap_months,))
        thr, pct = [], []
        for r in cur.fetchall():
            thr.append(int(r["thr"]))
            pct.append(float(r["pct"]) if r["pct"] is not None else 0.0)
        res["achilles_like"]["cumulative_observation"] = {"months_threshold": thr, "pct_persons": pct}

        # 6) Continuous Observation by Year
        cur.execute(f"""
            WITH per AS (
                SELECT
                    person_id,
                    MIN(observation_period_start_date) AS obs_start,
                    MAX(observation_period_end_date) AS obs_end
                FROM {obs_table}
                GROUP BY person_id
            ),
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
        """)
        yrs, nps = [], []
        for r in cur.fetchall():
            yrs.append(int(r["year"]))
            nps.append(int(r["n_persons"]))
        res["achilles_like"]["continuous_observation_by_year"] = {"year": yrs, "n_persons": nps}

    return res
