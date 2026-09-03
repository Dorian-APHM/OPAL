"""Query layer for the standalone bricks.

The analysis engines under ``backend/modules`` are reused as-is. What the
FastAPI routers add on top of them — a handful of catalogue queries and two SQL
assemblies that stitch a cohort to a date column — is reproduced here without
the HTTP, auth and app-DB plumbing.

All SQL is authored once with psycopg2-style ``%s`` placeholders and routed
through the CDM's :class:`~db.dialects.base.Dialect`, so the bricks work on
PostgreSQL, Oracle and SQL Server exactly like the server does. Identifiers go
through ``safe_identifier()`` and then the dialect's quoting.
"""
from __future__ import annotations

import logging
import re

from config import DOMAIN_CONFIG
from modules.cohort.sql_builder import build_cohort_sql
from opal_standalone.omop import fetch_all, fetch_one, table_ref
from utils.cdm_helper import SchemaMap, get_domain_config
from utils.sql_safety import safe_identifier

logger = logging.getLogger(__name__)

_ALLOWED_FIRST_KEYWORDS = ("SELECT", "WITH", "EXPLAIN")
_BLOCKED_KEYWORDS = (
    "INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE ",
    "TRUNCATE ", "GRANT ", "REVOKE ", "COPY ",
)


def dialect_of(schema_or_conn):
    """The dialect carried by a connection or a schema map (PostgreSQL default)."""
    from db.dialects import get_dialect

    dialect = getattr(schema_or_conn, "dialect", None) or getattr(
        schema_or_conn, "_dialect", None
    )
    return dialect or get_dialect("postgresql")


def _col(dialect, name: str) -> str:
    """Validated, engine-quoted column identifier."""
    return dialect.quote_ident(safe_identifier(name))


# ── cohort → dated cohort (incidence / estimation) ───────────────────────

def dated_cohort_sql(criteria: dict, schema: SchemaMap) -> str:
    """Cohort SQL yielding ``person_id`` and ``cohort_start_date``.

    Port of ``modules.incidence.router._build_dated_cohort_sql``: the index date
    is the first event of the first inclusion criterion that belongs to a
    clinical domain, falling back to the observation period start.
    """
    base_sql = build_cohort_sql(criteria, schema)

    for criterion in criteria.get("inclusion", {}).get("criteria", []):
        cfg = DOMAIN_CONFIG.get(criterion.get("domain", ""))
        if cfg:
            return (
                f"SELECT base.person_id,\n"
                f"       MIN(t.{cfg['date_col']}) AS cohort_start_date\n"
                f"FROM ({base_sql}) base\n"
                f"JOIN {schema.t(cfg['table'])} t ON base.person_id = t.{cfg['person_id']}\n"
                f"GROUP BY base.person_id"
            )

    return (
        f"SELECT p.person_id, op.observation_period_start_date AS cohort_start_date\n"
        f"FROM ({base_sql}) p\n"
        f"JOIN {schema.t('observation_period')} op ON p.person_id = op.person_id"
    )


def kaplan_meier_sql(
    target_criteria: dict,
    outcome_criteria: dict,
    schema: SchemaMap,
    time_at_risk_end: int | None = None,
    strata: list[str] | None = None,
) -> str:
    """Individual-level survival data (port of ``modules.estimation.router._build_km_sql``).

    Date arithmetic, casts and ``LEAST`` go through the dialect, so the query is
    engine-correct on Oracle and SQL Server as well as PostgreSQL.
    """
    dia = dialect_of(schema)
    target_sql = build_cohort_sql(target_criteria, schema)
    outcome_sql = build_cohort_sql(outcome_criteria, schema)

    def _first_domain(criteria: dict):
        for criterion in criteria.get("inclusion", {}).get("criteria", []):
            cfg = DOMAIN_CONFIG.get(criterion.get("domain", ""))
            if cfg:
                return cfg
        return None

    target_cfg = _first_domain(target_criteria)
    outcome_cfg = _first_domain(outcome_criteria)

    exit_criteria = target_criteria.get("exit_criteria") or {}
    exit_type = exit_criteria.get("type", "end_of_observation")

    if time_at_risk_end is not None:
        tar_limit = dia.least(
            "op.observation_period_end_date", dia.date_add("cohort_start", int(time_at_risk_end))
        )
    else:
        tar_limit = "op.observation_period_end_date"
    if exit_type == "fixed_duration":
        duration = int(exit_criteria.get("duration_days", 365))
        tar_limit = dia.least(
            "op.observation_period_end_date", dia.date_add("cohort_start", duration)
        )

    if target_cfg:
        target_dated = (
            f"SELECT base.person_id, MIN(t.{target_cfg['date_col']}) AS cohort_start\n"
            f"FROM ({target_sql}) base\n"
            f"JOIN {schema.t(target_cfg['table'])} t ON base.person_id = t.person_id\n"
            f"GROUP BY base.person_id"
        )
    else:
        target_dated = (
            f"SELECT base.person_id, op.observation_period_start_date AS cohort_start\n"
            f"FROM ({target_sql}) base\n"
            f"JOIN {schema.t('observation_period')} op ON base.person_id = op.person_id"
        )

    if outcome_cfg:
        outcome_dated = (
            f"SELECT base.person_id, MIN(t.{outcome_cfg['date_col']}) AS outcome_date\n"
            f"FROM ({outcome_sql}) base\n"
            f"JOIN {schema.t(outcome_cfg['table'])} t ON base.person_id = t.person_id\n"
            f"GROUP BY base.person_id"
        )
    else:
        outcome_dated = (
            f"SELECT base.person_id, {dia.cast('NULL', 'date')} AS outcome_date\n"
            f"FROM ({outcome_sql}) base"
        )

    strata = strata or []
    col_exprs = []
    for stratum in strata:
        if stratum == "gender":
            col_exprs.append("COALESCE(gc.concept_name, 'Unknown') AS gender_name")
        elif stratum == "age_group":
            age = f"{dia.extract('YEAR', dia.cast('te.cohort_start', 'date'))} - p.year_of_birth"
            col_exprs.append(
                "CASE "
                f"WHEN {age} < 18 THEN '0-17' "
                f"WHEN {age} < 40 THEN '18-39' "
                f"WHEN {age} < 65 THEN '40-64' "
                "ELSE '65+' END AS age_group"
            )
    strata_select = (", " + ", ".join(col_exprs)) if col_exprs else ""
    strata_out = "".join(
        f", {s}_name" if s == "gender" else f", {s}"
        for s in strata if s in ("gender", "age_group")
    )

    oc_date = dia.cast("oe.outcome_date", "date")
    cs_date = dia.cast("te.cohort_start", "date")
    tar_date = dia.cast(f"({tar_limit})", "date")
    days_to_event = dia.cast(dia.date_diff_days(oc_date, cs_date), "float")
    days_to_tar = dia.cast(dia.date_diff_days(tar_date, cs_date), "float")

    return f"""
WITH target_entry AS (
    {target_dated}
),
outcome_entry AS (
    {outcome_dated}
),
survival_data AS (
    SELECT
        te.person_id,
        te.cohort_start,
        {tar_limit} AS tar_end,
        oe.outcome_date,
        CASE
            WHEN oe.outcome_date IS NOT NULL
                 AND {oc_date} >= {cs_date}
                 AND {oc_date} <= {tar_date}
            THEN 1 ELSE 0
        END AS had_event,
        CASE
            WHEN oe.outcome_date IS NOT NULL
                 AND {oc_date} >= {cs_date}
                 AND {oc_date} <= {tar_date}
            THEN {days_to_event}
            ELSE {days_to_tar}
        END AS time_days
        {strata_select}
    FROM target_entry te
    JOIN {schema.t('observation_period')} op
        ON te.person_id = op.person_id
        AND te.cohort_start BETWEEN op.observation_period_start_date AND op.observation_period_end_date
    JOIN {schema.t('person')} p ON te.person_id = p.person_id
    LEFT JOIN {schema.t('concept')} gc ON p.gender_concept_id = gc.concept_id
    LEFT JOIN outcome_entry oe ON te.person_id = oe.person_id
    WHERE {cs_date} < {tar_date}
)
SELECT person_id, time_days, had_event{strata_out}
FROM survival_data
WHERE time_days > 0
"""


# ── raw SQL (cohort SQL console) ─────────────────────────────────────────

def check_read_only_sql(sql: str) -> str:
    """Validate a user-supplied query is read-only; return it stripped.

    Same guard as the server's ``/api/cohorts/sql/execute``. The CDM session is
    also opened read-only where the engine supports it, so this is one of two locks.
    """
    stripped = sql.strip().rstrip(";")
    if not stripped:
        raise ValueError("Empty query")
    first = re.split(r"\s+", stripped, maxsplit=1)[0].upper()
    if first not in _ALLOWED_FIRST_KEYWORDS:
        raise ValueError("Only SELECT, WITH (CTE) and EXPLAIN queries are allowed")
    upper = stripped.upper()
    for keyword in _BLOCKED_KEYWORDS:
        if keyword in upper:
            raise ValueError(f"Forbidden keyword detected: {keyword.strip()}")
    return stripped


def run_read_only_sql(conn, sql: str, limit: int = 100) -> list[dict]:
    """Execute a validated read-only query, capping the row count per engine."""
    stripped = check_read_only_sql(sql)
    upper = stripped.upper()
    if "LIMIT" not in upper and "FETCH NEXT" not in upper and "ROWNUM" not in upper:
        stripped = f"{stripped}\n{conn.dialect.limit_offset(str(int(limit)), '0')}"
    return fetch_all(conn, stripped)


def count_persons(conn, criteria: dict, schema: SchemaMap) -> int:
    """Number of distinct persons matching a cohort definition."""
    from modules.cohort.sql_builder import build_count_sql

    row = fetch_one(conn, build_count_sql(criteria, schema))
    return int(row["patient_count"]) if row else 0


# ── vocabulary / concept explorer ────────────────────────────────────────

def search_concepts(
    conn,
    schema: SchemaMap,
    q: str = "",
    domain: str | None = None,
    vocabulary: str | None = None,
    standard_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Search the vocabulary by name, code or concept_id."""
    dialect = conn.dialect
    concept_tbl = table_ref(conn, schema, "concept")
    conditions: list[str] = []
    params: list = []

    q = (q or "").strip()
    if q:
        if q.isdigit():
            conditions.append(
                "(c.concept_id = %s OR c.concept_code = %s OR "
                + dialect.ilike("c.concept_code", "%s") + ")"
            )
            params.extend([int(q), q, f"%{q}%"])
        else:
            conditions.append(
                "(" + dialect.ilike("c.concept_name", "%s")
                + " OR " + dialect.ilike("c.concept_code", "%s") + ")"
            )
            params.extend([f"%{q}%", f"%{q}%"])
    if domain:
        conditions.append("c.domain_id = %s")
        params.append(domain)
    if vocabulary:
        conditions.append("c.vocabulary_id = %s")
        params.append(vocabulary)
    if standard_only:
        conditions.append("c.standard_concept = 'S'")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    # Pagination is rendered by the dialect with the (validated) ints inlined, so
    # the textual order of LIMIT/OFFSET can differ per engine without disturbing
    # positional parameter binding.
    pagination = dialect.limit_offset(str(int(limit)), str(int(offset)))
    sql = f"""
        SELECT c.concept_id, c.concept_name, c.concept_code,
               c.domain_id, c.vocabulary_id, c.concept_class_id,
               c.standard_concept,
               {dialect.cast('c.valid_start_date', 'text')} AS valid_start_date,
               {dialect.cast('c.valid_end_date', 'text')} AS valid_end_date,
               c.invalid_reason,
               COUNT(*) OVER() AS total_count
        FROM {concept_tbl} c
        {where}
        ORDER BY c.concept_name
        {pagination}
    """
    rows = fetch_all(conn, sql, params)
    total = int(rows[0]["total_count"]) if rows else 0
    for row in rows:
        row.pop("total_count", None)
    return {"concepts": rows, "total": total, "limit": limit, "offset": offset}


def concept_details(conn, schema: SchemaMap, concept_id: int) -> dict | None:
    dialect = conn.dialect
    concept = fetch_one(
        conn,
        f"""
        SELECT concept_id, concept_name, concept_code, domain_id, vocabulary_id,
               concept_class_id, standard_concept,
               {dialect.cast('valid_start_date', 'text')} AS valid_start_date,
               {dialect.cast('valid_end_date', 'text')} AS valid_end_date,
               invalid_reason
        FROM {table_ref(conn, schema, 'concept')} WHERE concept_id = %s
        """,
        [int(concept_id)],
    )
    if not concept:
        return None
    relationships = fetch_all(
        conn,
        f"""
        SELECT cr.relationship_id,
               c2.concept_id AS related_concept_id,
               c2.concept_name AS related_concept_name,
               c2.vocabulary_id AS related_vocabulary_id,
               c2.concept_class_id AS related_concept_class_id,
               c2.standard_concept AS related_standard_concept
        FROM {table_ref(conn, schema, 'concept_relationship')} cr
        JOIN {table_ref(conn, schema, 'concept')} c2 ON c2.concept_id = cr.concept_id_2
        WHERE cr.concept_id_1 = %s AND cr.invalid_reason IS NULL
        ORDER BY cr.relationship_id, c2.concept_name
        {dialect.limit_offset('200', '0')}
        """,
        [int(concept_id)],
    )
    return {"concept": concept, "relationships": relationships}


def concept_hierarchy(conn, schema: SchemaMap, concept_id: int) -> dict:
    dialect = conn.dialect
    ancestor_tbl = table_ref(conn, schema, "concept_ancestor")
    concept_tbl = table_ref(conn, schema, "concept")
    ancestors = fetch_all(
        conn,
        f"""
        SELECT ca.ancestor_concept_id AS concept_id, c.concept_name, c.concept_code,
               c.vocabulary_id, c.concept_class_id, c.standard_concept,
               ca.min_levels_of_separation, ca.max_levels_of_separation
        FROM {ancestor_tbl} ca
        JOIN {concept_tbl} c ON c.concept_id = ca.ancestor_concept_id
        WHERE ca.descendant_concept_id = %s AND ca.ancestor_concept_id != %s
        ORDER BY ca.min_levels_of_separation
        {dialect.limit_offset('100', '0')}
        """,
        [int(concept_id), int(concept_id)],
    )
    descendants = fetch_all(
        conn,
        f"""
        SELECT ca.descendant_concept_id AS concept_id, c.concept_name, c.concept_code,
               c.vocabulary_id, c.concept_class_id, c.standard_concept,
               ca.min_levels_of_separation, ca.max_levels_of_separation
        FROM {ancestor_tbl} ca
        JOIN {concept_tbl} c ON c.concept_id = ca.descendant_concept_id
        WHERE ca.ancestor_concept_id = %s AND ca.descendant_concept_id != %s
        ORDER BY ca.min_levels_of_separation, c.concept_name
        {dialect.limit_offset('200', '0')}
        """,
        [int(concept_id), int(concept_id)],
    )
    return {"ancestors": ancestors, "descendants": descendants}


def concept_source_values(conn, schema: SchemaMap, concept_id: int) -> list[dict]:
    """Source values across clinical tables that map to a concept."""
    dialect = conn.dialect
    results: list[dict] = []
    for domain_name in DOMAIN_CONFIG:
        cfg = get_domain_config(conn, schema, domain_name)
        if not cfg or not cfg.get("source_value"):
            continue
        source_col = _col(dialect, cfg["source_value"])
        where_parts = [f"{_col(dialect, cfg['concept_id'])} = %s"]
        params: list = [domain_name, int(concept_id)]
        if cfg.get("source_concept_id"):
            where_parts.append(f"{_col(dialect, cfg['source_concept_id'])} = %s")
            params.append(int(concept_id))
        try:
            results.extend(
                fetch_all(
                    conn,
                    f"""
                    SELECT %s AS domain, {source_col} AS source_value,
                           COUNT(*) AS n_records, COUNT(DISTINCT person_id) AS n_persons
                    FROM {table_ref(conn, schema, cfg['table'])}
                    WHERE ({' OR '.join(where_parts)}) AND {source_col} IS NOT NULL
                    GROUP BY {source_col}
                    ORDER BY COUNT(*) DESC
                    {dialect.limit_offset('50', '0')}
                    """,
                    params,
                )
            )
        except Exception:
            logger.warning(
                "Source values unavailable for concept %s in %s", concept_id, domain_name,
                exc_info=True,
            )
            conn.rollback()
    return results


def list_vocabularies(conn, schema: SchemaMap) -> list[str]:
    rows = fetch_all(
        conn,
        f"SELECT DISTINCT vocabulary_id FROM {table_ref(conn, schema, 'concept')} "
        f"WHERE vocabulary_id IS NOT NULL ORDER BY vocabulary_id",
    )
    return [r["vocabulary_id"] for r in rows]


def list_concept_domains(conn, schema: SchemaMap) -> list[str]:
    rows = fetch_all(
        conn,
        f"SELECT DISTINCT domain_id FROM {table_ref(conn, schema, 'concept')} "
        f"WHERE domain_id IS NOT NULL ORDER BY domain_id",
    )
    return [r["domain_id"] for r in rows]


# ── concept sets ─────────────────────────────────────────────────────────

def resolve_concepts(conn, schema: SchemaMap, concepts: list[dict]) -> list[int]:
    """Expand a concept list to all concept_ids, descendants included."""
    all_ids: set[int] = set()
    expand: list[int] = []
    for concept in concepts:
        cid = int(concept["concept_id"] if isinstance(concept, dict) else concept)
        all_ids.add(cid)
        if not isinstance(concept, dict) or concept.get("include_descendants", True):
            expand.append(cid)
    if expand:
        fragment, params = conn.dialect.in_list("ancestor_concept_id", expand)
        rows = fetch_all(
            conn,
            f"SELECT DISTINCT descendant_concept_id FROM "
            f"{table_ref(conn, schema, 'concept_ancestor')} WHERE {fragment}",
            params,
        )
        all_ids.update(int(r["descendant_concept_id"]) for r in rows)
    return sorted(all_ids)


def concept_counts(conn, schema: SchemaMap, concept_ids: list[int]) -> list[dict]:
    """Record and person counts per domain for a list of concept_ids."""
    if not concept_ids:
        return []
    dialect = conn.dialect
    ids = [int(c) for c in concept_ids]
    counts: list[dict] = []
    for domain_name, cfg in DOMAIN_CONFIG.items():
        fragment, params = dialect.in_list(_col(dialect, cfg["concept_id"]), ids)
        try:
            rows = fetch_all(
                conn,
                f"SELECT COUNT(*) AS n_records, "
                f"COUNT(DISTINCT {_col(dialect, cfg['person_id'])}) AS n_persons "
                f"FROM {table_ref(conn, schema, cfg['table'])} WHERE {fragment}",
                params,
            )
        except Exception:
            conn.rollback()
            continue
        if rows and int(rows[0]["n_records"] or 0) > 0:
            counts.append({
                "domain": domain_name,
                "n_records": int(rows[0]["n_records"]),
                "n_persons": int(rows[0]["n_persons"]),
            })
    return counts


# ── mapping ──────────────────────────────────────────────────────────────

def mapping_summary(conn, schema: SchemaMap, domain: str) -> dict:
    """Term- and row-level mapping coverage for a clinical domain."""
    dialect = conn.dialect
    cfg = get_domain_config(conn, schema, domain)
    if not cfg or not cfg.get("source_value"):
        return {}
    concept_col = _col(dialect, cfg["concept_id"])
    source_col = _col(dialect, cfg["source_value"])
    row = fetch_one(
        conn,
        f"""
        SELECT COUNT(*) AS total_rows,
               COUNT(CASE WHEN {concept_col} != 0 THEN 1 END) AS mapped_rows,
               COUNT(DISTINCT {source_col}) AS total_terms,
               COUNT(DISTINCT CASE WHEN {concept_col} != 0 THEN {source_col} END) AS mapped_terms
        FROM {table_ref(conn, schema, cfg['table'])}
        """,
    )
    total_rows = int(row["total_rows"] or 0)
    mapped_rows = int(row["mapped_rows"] or 0)
    total_terms = int(row["total_terms"] or 0)
    mapped_terms = int(row["mapped_terms"] or 0)
    return {
        "domain": domain,
        "total_rows": total_rows,
        "mapped_rows": mapped_rows,
        "unmapped_rows": total_rows - mapped_rows,
        "pct_rows_mapped": (mapped_rows / total_rows * 100) if total_rows else None,
        "total_terms": total_terms,
        "mapped_terms": mapped_terms,
        "unmapped_terms": total_terms - mapped_terms,
        "pct_terms_mapped": (mapped_terms / total_terms * 100) if total_terms else None,
    }


def unmapped_terms(
    conn, schema: SchemaMap, domain: str, limit: int = 100, search: str = ""
) -> list[dict]:
    """Most frequent unmapped source values of a domain (optionally filtered).

    The server reads this from the app-DB source-value cache; standalone has no
    such cache, so it queries the CDM directly — through the dialect, so the
    query is engine-correct rather than PostgreSQL-only.
    """
    dialect = conn.dialect
    cfg = get_domain_config(conn, schema, domain)
    if not cfg or not cfg.get("source_value"):
        return []

    source_col = _col(dialect, cfg["source_value"])
    select_parts = [f"{source_col} AS source_value"]
    if cfg.get("source_name"):
        select_parts.append(f"MIN({_col(dialect, cfg['source_name'])}) AS source_name")
    if cfg.get("source_atc"):
        select_parts.append(f"MIN({_col(dialect, cfg['source_atc'])}) AS source_atc")
    select_parts.append("COUNT(*) AS n_records")
    select_parts.append(f"COUNT(DISTINCT {_col(dialect, cfg['person_id'])}) AS n_persons")

    wheres = [f"{_col(dialect, cfg['concept_id'])} = 0"]
    params: list = []
    if search:
        like_parts = [dialect.ilike(source_col, "%s")]
        params.append(f"%{search}%")
        if cfg.get("source_name"):
            like_parts.append(dialect.ilike(_col(dialect, cfg["source_name"]), "%s"))
            params.append(f"%{search}%")
        wheres.append("(" + " OR ".join(like_parts) + ")")

    sql = f"""
        SELECT {', '.join(select_parts)}
        FROM {table_ref(conn, schema, cfg['table'])}
        WHERE {' AND '.join(wheres)}
        GROUP BY {source_col}
        ORDER BY COUNT(*) DESC
        {dialect.limit_offset(str(int(limit)), '0')}
    """
    return fetch_all(conn, sql, params)


def mappable_domains(conn, schema: SchemaMap) -> list[str]:
    """Clinical domains that exist in this CDM and expose a source value."""
    return [
        domain
        for domain, cfg in DOMAIN_CONFIG.items()
        if cfg.get("source_value") and table_exists(conn, schema, cfg["table"])
    ]


def table_exists(conn, schema: SchemaMap, table: str) -> bool:
    """Whether ``table`` exists in the CDM (asked of the engine's own catalog)."""
    try:
        return conn.dialect.table_exists(conn, schema.schema_for(table), table)
    except Exception:
        conn.rollback()
        return False


# ── cohort criteria validation ───────────────────────────────────────────

MAX_CRITERIA_DEPTH = 5
MAX_CONCEPT_IDS = 1000


def validate_criteria(criteria: dict, _depth: int = 0) -> dict:
    """Structural validation of a cohort definition (port of the server's guard).

    Rejects excessive nesting, oversized concept lists and the ``nested_cohort_sql``
    field that used to allow raw SQL injection into the builder.
    """
    if _depth > MAX_CRITERIA_DEPTH:
        raise ValueError(f"Criteria nesting depth exceeds maximum of {MAX_CRITERIA_DEPTH}")
    if not isinstance(criteria, dict):
        raise ValueError("Criteria must be a JSON object")

    for group_key in ("inclusion", "exclusion"):
        group = criteria.get(group_key)
        if group is None:
            continue
        if not isinstance(group, dict):
            raise ValueError(f"'{group_key}' must be a JSON object")
        for criterion in group.get("criteria", []):
            if not isinstance(criterion, dict):
                raise ValueError(f"Each criterion in '{group_key}' must be a JSON object")
            if "nested_cohort_sql" in criterion:
                raise ValueError("Unsupported field 'nested_cohort_sql' in criterion")
            concepts = criterion.get("concepts", [])
            if not isinstance(concepts, list):
                raise ValueError("concepts must be a list")
            if len(concepts) > MAX_CONCEPT_IDS:
                raise ValueError(
                    f"concepts count ({len(concepts)}) exceeds maximum of {MAX_CONCEPT_IDS}"
                )
            for concept in concepts:
                cid = concept.get("concept_id") if isinstance(concept, dict) else concept
                if not isinstance(cid, (int, float)) or isinstance(cid, bool):
                    raise ValueError("concept_id must be an integer")
        for sub_group in group.get("groups", []):
            validate_criteria({"inclusion": sub_group}, _depth=_depth + 1)
    return criteria
