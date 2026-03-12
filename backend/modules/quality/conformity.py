"""
CDM Conformity Validation.

Runs structural checks on the OMOP CDM and returns a conformity report
with scores and detailed findings. Integrated into the quality analysis.
"""
import logging
import re

logger = logging.getLogger(__name__)

_SAFE_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe(name: str) -> str:
    if not _SAFE_ID_RE.match(name):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


def run_conformity_checks(conn, omop_schema: str = "omop_cdm") -> dict:
    """
    Run CDM conformity validation checks.

    Returns:
        {
            "score": float (0-100),
            "total_checks": int,
            "passed": int,
            "warnings": int,
            "failures": int,
            "checks": [
                {
                    "id": str,
                    "category": str,
                    "description": str,
                    "status": "pass" | "warning" | "fail",
                    "detail": str,
                    "value": any,
                }
            ]
        }
    """
    schema = _safe(omop_schema)
    checks = []

    with conn.cursor() as cur:
        # ── 1. Required tables exist ──
        required_tables = [
            "person", "observation_period", "visit_occurrence",
            "condition_occurrence", "drug_exposure", "measurement",
            "procedure_occurrence", "observation", "concept", "vocabulary",
        ]
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
        """, (schema,))
        existing_tables = {r[0] for r in cur.fetchall()}

        for table in required_tables:
            present = table in existing_tables
            checks.append({
                "id": f"table_exists_{table}",
                "category": "Structure",
                "description": f"Table '{table}' exists",
                "status": "pass" if present else "fail",
                "detail": "" if present else f"Missing required table: {table}",
                "value": present,
            })

        # ── 2. Person table checks ──
        if "person" in existing_tables:
            # Persons with no observation period
            cur.execute(f"""
                SELECT COUNT(*) FROM {schema}.person p
                LEFT JOIN {schema}.observation_period op ON op.person_id = p.person_id
                WHERE op.person_id IS NULL
            """)
            orphan_persons = cur.fetchone()[0]
            cur.execute(f"SELECT COUNT(*) FROM {schema}.person")
            total_persons = cur.fetchone()[0]

            pct_orphan = round((orphan_persons / total_persons * 100), 2) if total_persons > 0 else 0
            status = "pass" if pct_orphan < 1 else ("warning" if pct_orphan < 10 else "fail")
            checks.append({
                "id": "persons_without_obs_period",
                "category": "Completeness",
                "description": "Persons without observation period",
                "status": status,
                "detail": f"{orphan_persons:,} persons ({pct_orphan}%) have no observation period",
                "value": {"count": orphan_persons, "pct": pct_orphan},
            })

            # Future birth years
            cur.execute(f"""
                SELECT COUNT(*) FROM {schema}.person
                WHERE year_of_birth > EXTRACT(YEAR FROM CURRENT_DATE)
            """)
            future_births = cur.fetchone()[0]
            checks.append({
                "id": "future_birth_years",
                "category": "Plausibility",
                "description": "Persons with future birth year",
                "status": "pass" if future_births == 0 else "fail",
                "detail": f"{future_births:,} persons have birth year in the future" if future_births else "",
                "value": future_births,
            })

            # gender_concept_id = 0 (unmapped gender)
            cur.execute(f"""
                SELECT COUNT(*) FROM {schema}.person WHERE gender_concept_id = 0 OR gender_concept_id IS NULL
            """)
            unmapped_gender = cur.fetchone()[0]
            pct_gender = round((unmapped_gender / total_persons * 100), 2) if total_persons > 0 else 0
            status = "pass" if pct_gender < 1 else ("warning" if pct_gender < 5 else "fail")
            checks.append({
                "id": "unmapped_gender",
                "category": "Completeness",
                "description": "Persons with unmapped gender (concept_id=0)",
                "status": status,
                "detail": f"{unmapped_gender:,} persons ({pct_gender}%) have unmapped gender",
                "value": {"count": unmapped_gender, "pct": pct_gender},
            })

        # ── 3. Observation period checks ──
        if "observation_period" in existing_tables:
            # Overlapping observation periods
            cur.execute(f"""
                SELECT COUNT(*) FROM (
                    SELECT person_id FROM {schema}.observation_period
                    GROUP BY person_id
                    HAVING COUNT(*) > 1
                ) t
            """)
            multi_obs = cur.fetchone()[0]
            checks.append({
                "id": "multiple_obs_periods",
                "category": "Conformance",
                "description": "Persons with multiple observation periods",
                "status": "pass" if multi_obs == 0 else "warning",
                "detail": f"{multi_obs:,} persons have multiple observation periods" if multi_obs else "",
                "value": multi_obs,
            })

            # Future observation end dates
            cur.execute(f"""
                SELECT COUNT(*) FROM {schema}.observation_period
                WHERE observation_period_end_date > CURRENT_DATE + INTERVAL '1 day'
            """)
            future_obs = cur.fetchone()[0]
            checks.append({
                "id": "future_obs_end_dates",
                "category": "Plausibility",
                "description": "Observation periods ending in the future",
                "status": "pass" if future_obs == 0 else "warning",
                "detail": f"{future_obs:,} observation periods end in the future" if future_obs else "",
                "value": future_obs,
            })

        # ── 4. Clinical tables: concept_id = 0 checks ──
        clinical_tables = {
            "condition_occurrence": "condition_concept_id",
            "drug_exposure": "drug_concept_id",
            "measurement": "measurement_concept_id",
            "procedure_occurrence": "procedure_concept_id",
            "observation": "observation_concept_id",
        }

        for table, concept_col in clinical_tables.items():
            if table not in existing_tables:
                continue
            try:
                cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
                total = cur.fetchone()[0]
                if total == 0:
                    checks.append({
                        "id": f"unmapped_concepts_{table}",
                        "category": "Completeness",
                        "description": f"{table}: unmapped concepts (concept_id=0)",
                        "status": "warning",
                        "detail": f"Table {table} is empty",
                        "value": {"count": 0, "pct": 0, "total": 0},
                    })
                    continue

                cur.execute(f"SELECT COUNT(*) FROM {schema}.{table} WHERE {concept_col} = 0")
                unmapped = cur.fetchone()[0]
                pct = round((unmapped / total * 100), 2) if total > 0 else 0
                status = "pass" if pct < 5 else ("warning" if pct < 20 else "fail")
                checks.append({
                    "id": f"unmapped_concepts_{table}",
                    "category": "Completeness",
                    "description": f"{table}: unmapped concepts (concept_id=0)",
                    "status": status,
                    "detail": f"{unmapped:,} / {total:,} records ({pct}%) have concept_id=0",
                    "value": {"count": unmapped, "pct": pct, "total": total},
                })
            except Exception as e:
                logger.warning("Check failed for %s: %s", table, e)

        # ── 5. Future dates ──
        date_checks = {
            "condition_occurrence": "condition_start_date",
            "drug_exposure": "drug_exposure_start_date",
            "measurement": "measurement_date",
            "procedure_occurrence": "procedure_date",
            "visit_occurrence": "visit_start_date",
        }

        for table, date_col in date_checks.items():
            if table not in existing_tables:
                continue
            try:
                cur.execute(f"""
                    SELECT COUNT(*) FROM {schema}.{table}
                    WHERE {date_col} > CURRENT_DATE + INTERVAL '1 day'
                """)
                future = cur.fetchone()[0]
                checks.append({
                    "id": f"future_dates_{table}",
                    "category": "Plausibility",
                    "description": f"{table}: records with future dates",
                    "status": "pass" if future == 0 else ("warning" if future < 100 else "fail"),
                    "detail": f"{future:,} records have dates in the future" if future else "",
                    "value": future,
                })
            except Exception as e:
                logger.warning("Date check failed for %s: %s", table, e)

        # ── 6. Visit orphans (clinical records without matching visit) ──
        visit_fk_checks = {
            "condition_occurrence": "visit_occurrence_id",
            "drug_exposure": "visit_occurrence_id",
            "measurement": "visit_occurrence_id",
        }

        if "visit_occurrence" in existing_tables:
            for table, fk_col in visit_fk_checks.items():
                if table not in existing_tables:
                    continue
                try:
                    cur.execute(f"""
                        SELECT COUNT(*) FROM {schema}.{table} t
                        WHERE t.{fk_col} IS NOT NULL
                        AND NOT EXISTS (
                            SELECT 1 FROM {schema}.visit_occurrence v
                            WHERE v.visit_occurrence_id = t.{fk_col}
                        )
                    """)
                    orphans = cur.fetchone()[0]
                    checks.append({
                        "id": f"visit_orphans_{table}",
                        "category": "Conformance",
                        "description": f"{table}: records with invalid visit_occurrence_id",
                        "status": "pass" if orphans == 0 else ("warning" if orphans < 100 else "fail"),
                        "detail": f"{orphans:,} records reference non-existent visits" if orphans else "",
                        "value": orphans,
                    })
                except Exception as e:
                    logger.warning("Visit FK check failed for %s: %s", table, e)

    # Calculate score
    total_checks = len(checks)
    passed = sum(1 for c in checks if c["status"] == "pass")
    warnings = sum(1 for c in checks if c["status"] == "warning")
    failures = sum(1 for c in checks if c["status"] == "fail")
    score = round((passed / total_checks * 100), 1) if total_checks > 0 else 0

    return {
        "score": score,
        "total_checks": total_checks,
        "passed": passed,
        "warnings": warnings,
        "failures": failures,
        "checks": checks,
    }
