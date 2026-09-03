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


# Steps for progress tracking (label, total_steps)
_CONFORMITY_STEPS = [
    "structure",
    "person",
    "observation_period",
    "condition_occurrence",
    "drug_exposure",
    "measurement",
    "procedure_occurrence",
    "observation",
    "visit_occurrence",
]


def run_conformity_checks(conn, omop_schema: str = "omop_cdm", on_progress=None) -> dict:
    """
    Run CDM conformity validation checks.

    Args:
        conn: psycopg2 connection to the OMOP CDM.
        omop_schema: Schema name for the OMOP CDM.
        on_progress: Optional callback ``(step_name, completed, total)`` called
            after each major step completes.

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
    def _schema_for(table: str) -> str:
        """Validated schema name that holds ``table`` (category-aware)."""
        name = omop_schema.schema_for(table) if hasattr(omop_schema, "schema_for") else omop_schema
        return _safe(name)

    # All data-level conformity queries below touch clinical tables, which share
    # the same category schema.
    clinical_schema = _schema_for("person")
    dialect = conn.dialect

    def _ref(table: str, schema: str = None) -> str:
        return f"{dialect.quote_ident(schema or clinical_schema)}.{dialect.quote_ident(table)}"

    checks = []
    total_steps = len(_CONFORMITY_STEPS)
    completed = 0

    def _progress(step_name):
        nonlocal completed
        completed += 1
        if on_progress:
            on_progress(step_name, completed, total_steps)

    with conn.cursor() as cur:
        # ── 1. Required tables exist ──
        required_tables = [
            "person", "observation_period", "visit_occurrence",
            "condition_occurrence", "drug_exposure", "measurement",
            "procedure_occurrence", "observation", "concept", "vocabulary",
        ]
        # Required tables may live in different schemas (e.g. concept/vocabulary
        # in a dedicated vocabulary schema). Query each distinct schema once and
        # check each table against the schema that holds its category.
        present_by_schema: dict[str, set] = {}
        for sch in {_schema_for(t) for t in required_tables}:
            present_by_schema[sch] = dialect.list_tables(conn, sch)
        existing_tables = {
            t for t in required_tables
            if t in present_by_schema.get(_schema_for(t), set())
        }

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

        _progress("structure")

        # ── 2. Person table checks ──
        if "person" in existing_tables:
            # Merge person checks into fewer queries (P14 fix)
            cur.execute(f"""
                SELECT
                    COUNT(*) AS total,
                    {dialect.count_filter("gender_concept_id = 0 OR gender_concept_id IS NULL")} AS unmapped_gender,
                    {dialect.count_filter(f"year_of_birth > {dialect.extract('YEAR', dialect.current_date())}")} AS future_births
                FROM {_ref("person")}
            """)
            row = cur.fetchone()
            total_persons = row[0]
            unmapped_gender = row[1]
            future_births = row[2]

            # Persons with no observation period (requires join, separate query)
            if "observation_period" in existing_tables:
                cur.execute(f"""
                    SELECT COUNT(*) FROM {_ref("person")} p
                    LEFT JOIN {_ref("observation_period")} op ON op.person_id = p.person_id
                    WHERE op.person_id IS NULL
                """)
                orphan_persons = cur.fetchone()[0]
            else:
                orphan_persons = total_persons

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

            checks.append({
                "id": "future_birth_years",
                "category": "Plausibility",
                "description": "Persons with future birth year",
                "status": "pass" if future_births == 0 else "fail",
                "detail": f"{future_births:,} persons have birth year in the future" if future_births else "",
                "value": future_births,
            })

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

        _progress("person")

        # ── 3. Observation period checks ──
        if "observation_period" in existing_tables:
            # Merge both obs period checks into one query (P14 fix)
            cur.execute(f"""
                SELECT
                    (SELECT COUNT(*) FROM (
                        SELECT person_id FROM {_ref("observation_period")}
                        GROUP BY person_id HAVING COUNT(*) > 1
                    ) t) AS multi_obs,
                    (SELECT COUNT(*) FROM {_ref("observation_period")}
                     WHERE observation_period_end_date > {dialect.date_add(dialect.current_date(), 1)}) AS future_obs
            """)
            row = cur.fetchone()
            multi_obs = row[0]
            future_obs = row[1]

            checks.append({
                "id": "multiple_obs_periods",
                "category": "Conformance",
                "description": "Persons with multiple observation periods",
                "status": "pass" if multi_obs == 0 else "warning",
                "detail": f"{multi_obs:,} persons have multiple observation periods" if multi_obs else "",
                "value": multi_obs,
            })
            checks.append({
                "id": "future_obs_end_dates",
                "category": "Plausibility",
                "description": "Observation periods ending in the future",
                "status": "pass" if future_obs == 0 else "warning",
                "detail": f"{future_obs:,} observation periods end in the future" if future_obs else "",
                "value": future_obs,
            })

        _progress("observation_period")

        # ── 4/5/6. Clinical tables: merged concept_id, date, and visit FK checks (P14 fix) ──
        # Unified config: each clinical table with its concept_col, date_col, visit_fk_col
        clinical_checks_config = {
            "condition_occurrence": {
                "concept_col": "condition_concept_id",
                "date_col": "condition_start_date",
                "visit_fk_col": "visit_occurrence_id",
            },
            "drug_exposure": {
                "concept_col": "drug_concept_id",
                "date_col": "drug_exposure_start_date",
                "visit_fk_col": "visit_occurrence_id",
            },
            "measurement": {
                "concept_col": "measurement_concept_id",
                "date_col": "measurement_date",
                "visit_fk_col": "visit_occurrence_id",
            },
            "procedure_occurrence": {
                "concept_col": "procedure_concept_id",
                "date_col": "procedure_date",
                "visit_fk_col": None,
            },
            "observation": {
                "concept_col": "observation_concept_id",
                "date_col": None,
                "visit_fk_col": None,
            },
        }
        has_visits = "visit_occurrence" in existing_tables

        for table, cfg in clinical_checks_config.items():
            if table not in existing_tables:
                _progress(table)
                continue

            concept_col = cfg["concept_col"]
            date_col = cfg["date_col"]
            visit_fk_col = cfg["visit_fk_col"]

            try:
                # Build a single query with FILTER clauses for all checks on this table
                concept_id_q = dialect.quote_ident(concept_col)
                filter_parts = ["COUNT(*) AS total"]
                filter_parts.append(f"{dialect.count_filter(f'{concept_id_q} = 0')} AS unmapped")

                if date_col:
                    date_q = dialect.quote_ident(date_col)
                    filter_parts.append(
                        f"{dialect.count_filter(f'{date_q} > {dialect.date_add(dialect.current_date(), 1)}')} AS future_dates"
                    )

                if visit_fk_col and has_visits:
                    vfk = dialect.quote_ident(visit_fk_col)
                    cond = (f"{vfk} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {_ref('visit_occurrence')} v"
                            f" WHERE v.visit_occurrence_id = t.{vfk})")
                    filter_parts.append(f"{dialect.count_filter(cond)} AS orphans")

                select_clause = ",\n                       ".join(filter_parts)
                cur.execute(f"SELECT {select_clause} FROM {_ref(table)} t")
                row = cur.fetchone()

                total = row[0]
                unmapped = row[1]
                idx = 2

                if total == 0:
                    checks.append({
                        "id": f"unmapped_concepts_{table}",
                        "category": "Completeness",
                        "description": f"{table}: unmapped concepts (concept_id=0)",
                        "status": "warning",
                        "detail": f"Table {table} is empty",
                        "value": {"count": 0, "pct": 0, "total": 0},
                    })
                    _progress(table)
                    continue

                # Concept check
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

                # Future dates check
                if date_col:
                    future = row[idx]
                    idx += 1
                    checks.append({
                        "id": f"future_dates_{table}",
                        "category": "Plausibility",
                        "description": f"{table}: records with future dates",
                        "status": "pass" if future == 0 else ("warning" if future < 100 else "fail"),
                        "detail": f"{future:,} records have dates in the future" if future else "",
                        "value": future,
                    })

                # Visit orphan check
                if visit_fk_col and has_visits:
                    orphans = row[idx]
                    checks.append({
                        "id": f"visit_orphans_{table}",
                        "category": "Conformance",
                        "description": f"{table}: records with invalid visit_occurrence_id",
                        "status": "pass" if orphans == 0 else ("warning" if orphans < 100 else "fail"),
                        "detail": f"{orphans:,} records reference non-existent visits" if orphans else "",
                        "value": orphans,
                    })

            except Exception as e:
                logger.warning("Conformity check failed for %s: %s", table, e)

            _progress(table)

        # ── Visit occurrence future dates (standalone, no concept/FK checks) ──
        if "visit_occurrence" in existing_tables:
            try:
                cur.execute(f"""
                    SELECT COUNT(*) FROM {_ref("visit_occurrence")}
                    WHERE visit_start_date > {dialect.date_add(dialect.current_date(), 1)}
                """)
                future = cur.fetchone()[0]
                checks.append({
                    "id": "future_dates_visit_occurrence",
                    "category": "Plausibility",
                    "description": "visit_occurrence: records with future dates",
                    "status": "pass" if future == 0 else ("warning" if future < 100 else "fail"),
                    "detail": f"{future:,} records have dates in the future" if future else "",
                    "value": future,
                })
            except Exception as e:
                logger.warning("Date check failed for visit_occurrence: %s", e)

        _progress("visit_occurrence")

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
