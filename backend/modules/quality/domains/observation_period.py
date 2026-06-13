"""
Observation Period domain analysis — ported from achilles_like/analysis.py.
All 6 sub-analyses preserved exactly.

Engine-neutral via the Dialect: AGE/MAKE_DATE/generate_series/casts are produced
by dialect helpers, so PostgreSQL keeps its native SQL while Oracle/SQL Server get
their own idioms (MONTHS_BETWEEN/DATEFROMPARTS/recursive CTE — best-effort).
"""
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
    dialect = conn.dialect
    cs = dialect.quote_ident(safe_identifier(clinical_schema))
    vs = dialect.quote_ident(safe_identifier(concept_schema))
    obs_ref = f"{cs}.{dialect.quote_ident('observation_period')}"
    person_ref = f"{cs}.{dialect.quote_ident('person')}"
    concept_ref = f"{vs}.{dialect.quote_ident('concept')}"

    obs_table_str = f"{clinical_schema}.observation_period"

    res = {
        "domain": "ObservationPeriod",
        "table": obs_table_str,
        "achilles_like": {},
        "mapping": {},
    }

    # Exact birth date: day/month_of_birth when available, fallback to July 1st.
    birth_date = dialect.make_date(
        "p.year_of_birth",
        "COALESCE(NULLIF(p.month_of_birth, 0), 7)",
        "COALESCE(NULLIF(p.day_of_birth, 0), 1)",
    )

    # Shared CTE fragment: per-person min/max observation dates
    per_cte = f"""
        per AS (
            SELECT
                person_id,
                MIN(observation_period_start_date) AS obs_start,
                MAX(observation_period_end_date) AS obs_end
            FROM {obs_ref}
            GROUP BY person_id
        )
    """

    # Reusable age/duration expressions (engine-aware)
    age_int = dialect.cast(dialect.age_years("per.obs_start", birth_date), "int")
    age_dec = f"{dialect.cast(dialect.date_diff_days('per.obs_start', birth_date), 'numeric')} / 365.25"

    def _months(end, start, typ):
        return dialect.cast(dialect.greatest("0", dialect.months_between(end, start)), typ)

    with dialect.dict_cursor(conn) as cur:
        # 1) Age at First Observation (integer years for histogram)
        dialect.execute(cur, f"""
            WITH {per_cte}
            SELECT
                {age_int} AS age,
                COUNT(*) AS n
            FROM per
            JOIN {person_ref} p ON p.person_id = per.person_id
            WHERE per.obs_start IS NOT NULL
              AND p.year_of_birth IS NOT NULL
              AND {dialect.age_years("per.obs_start", birth_date)} BETWEEN 0 AND 120
            GROUP BY 1
            ORDER BY age
        """)
        ages, counts = [], []
        for r in cur.fetchall():
            ages.append(int(r["age"]))
            counts.append(int(r["n"]))
        res["achilles_like"]["age_at_first_observation"] = {"age": ages, "count": counts}

        # 2) Age by Gender (exact decimal age for boxplot quantiles)
        dialect.execute(cur, f"""
            WITH {per_cte},
            ages AS (
                SELECT
                    p.person_id,
                    p.gender_concept_id,
                    {age_dec} AS age
                FROM per
                JOIN {person_ref} p ON p.person_id = per.person_id
                WHERE per.obs_start IS NOT NULL
                  AND p.year_of_birth IS NOT NULL
                  AND {age_dec} BETWEEN 0 AND 120
            )
            SELECT
                a.gender_concept_id,
                COALESCE(c.concept_name, 'UNKNOWN') AS gender_name,
                COUNT(*) AS n,
                AVG(a.age) AS mean_age,
                {dialect.percentile_cont(0.1, "a.age")} AS p10,
                {dialect.percentile_cont(0.25, "a.age")} AS p25,
                {dialect.percentile_cont(0.5, "a.age")} AS median_age,
                {dialect.percentile_cont(0.75, "a.age")} AS p75,
                {dialect.percentile_cont(0.9, "a.age")} AS p90
            FROM ages a
            LEFT JOIN {concept_ref} c ON c.concept_id = a.gender_concept_id
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
        dialect.execute(cur, f"""
            WITH {per_cte},
            per2 AS (
                SELECT
                    person_id,
                    {_months("obs_end", "obs_start", "int")} AS months
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
        dialect.execute(cur, f"""
            WITH {per_cte},
            per2 AS (
                SELECT
                    per.person_id,
                    {_months("per.obs_end", "per.obs_start", "numeric")} AS months
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
                {dialect.percentile_cont(0.1, "per2.months")} AS p10,
                {dialect.percentile_cont(0.25, "per2.months")} AS p25,
                {dialect.percentile_cont(0.5, "per2.months")} AS median_months,
                {dialect.percentile_cont(0.75, "per2.months")} AS p75,
                {dialect.percentile_cont(0.9, "per2.months")} AS p90
            FROM per2
            JOIN {person_ref} p ON p.person_id = per2.person_id
            LEFT JOIN {concept_ref} c ON c.concept_id = p.gender_concept_id
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

        # 5) Cumulative Observation (P11 fix: window function instead of correlated subquery)
        dialect.execute(cur, f"""
            WITH {per_cte},
            per2 AS (
                SELECT
                    {dialect.least(_months("obs_end", "obs_start", "int"), "%s")} AS months
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
            SELECT m AS thr, ROUND({dialect.cast("n_ge", "numeric")} / n_total * 100.0, 2) AS pct
            FROM cum
            ORDER BY m
        """, (cap_months,))
        thr, pct = [], []
        for r in cur.fetchall():
            thr.append(int(r["thr"]))
            pct.append(float(r["pct"]) if r["pct"] is not None else 0.0)
        res["achilles_like"]["cumulative_observation"] = {"months_threshold": thr, "pct_persons": pct}

        # 6) Continuous Observation by Year
        min_year = f"(SELECT MIN({dialect.cast(dialect.extract('YEAR', 'obs_start'), 'int')}) FROM per WHERE obs_start IS NOT NULL)"
        max_year = f"(SELECT MAX({dialect.cast(dialect.extract('YEAR', 'obs_end'), 'int')}) FROM per WHERE obs_end IS NOT NULL)"
        years_cte = dialect.int_series_cte("years", min_year, max_year)
        jan1 = dialect.make_date(dialect.cast("y.y", "int"), "1", "1")
        dec31 = dialect.make_date(dialect.cast("y.y", "int"), "12", "31")
        dialect.execute(cur, f"""
            WITH {per_cte},
            {years_cte}
            SELECT y.y AS year, COUNT(*) AS n_persons
            FROM years y
            JOIN per ON per.obs_start <= {jan1}
                    AND per.obs_end >= {dec31}
            GROUP BY y.y
            ORDER BY y.y
        """)
        yrs, nps = [], []
        for r in cur.fetchall():
            yrs.append(int(r["year"]))
            nps.append(int(r["n_persons"]))
        res["achilles_like"]["continuous_observation_by_year"] = {"year": yrs, "n_persons": nps}

    return res
