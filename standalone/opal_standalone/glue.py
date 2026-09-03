"""Query layer for the standalone bricks.

The analysis engines under ``backend/modules`` are reused as-is. What the
FastAPI routers add on top of them — a handful of catalogue queries and two SQL
assemblies that stitch a cohort to a date column — is reproduced here without
the HTTP, auth and app-DB plumbing. Anything that talks to the CDM goes through
``psycopg2.sql`` composition or bound parameters.
"""
from __future__ import annotations

import logging
import re

from psycopg2 import sql as psysql

from config import DOMAIN_CONFIG
from modules.cohort.sql_builder import build_cohort_sql
from opal_standalone.omop import fetch_all, fetch_one, has_unaccent
from utils.cdm_helper import SchemaMap, get_domain_config
from utils.sql_safety import safe_identifier

logger = logging.getLogger(__name__)

_ALLOWED_FIRST_KEYWORDS = ("SELECT", "WITH", "EXPLAIN")
_BLOCKED_KEYWORDS = (
    "INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE ",
    "TRUNCATE ", "GRANT ", "REVOKE ", "COPY ",
)


def _ident(name: str) -> psysql.Identifier:
    return psysql.Identifier(safe_identifier(name))


def _schema_ident(schema: SchemaMap, table: str) -> psysql.Identifier:
    return psysql.Identifier(safe_identifier(schema.schema_for(table)))


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
    """Individual-level survival data (port of ``modules.estimation.router._build_km_sql``)."""
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
        tar_limit = (
            "LEAST(op.observation_period_end_date, cohort_start + INTERVAL "
            f"'{int(time_at_risk_end)} days')"
        )
    else:
        tar_limit = "op.observation_period_end_date"
    if exit_type == "fixed_duration":
        duration = int(exit_criteria.get("duration_days", 365))
        tar_limit = (
            "LEAST(op.observation_period_end_date, cohort_start + INTERVAL "
            f"'{duration} days')"
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
            f"SELECT base.person_id, NULL::date AS outcome_date\n"
            f"FROM ({outcome_sql}) base"
        )

    strata = strata or []
    strata_select = ""
    col_exprs = []
    for stratum in strata:
        if stratum == "gender":
            col_exprs.append("COALESCE(gc.concept_name, 'Unknown') AS gender_name")
        elif stratum == "age_group":
            col_exprs.append(
                "CASE "
                "WHEN EXTRACT(YEAR FROM te.cohort_start::date) - p.year_of_birth < 18 THEN '0-17' "
                "WHEN EXTRACT(YEAR FROM te.cohort_start::date) - p.year_of_birth < 40 THEN '18-39' "
                "WHEN EXTRACT(YEAR FROM te.cohort_start::date) - p.year_of_birth < 65 THEN '40-64' "
                "ELSE '65+' END AS age_group"
            )
    if col_exprs:
        strata_select = ", " + ", ".join(col_exprs)
    strata_out = "".join(
        f", {s}_name" if s == "gender" else f", {s}" for s in strata if s in ("gender", "age_group")
    )

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
                 AND oe.outcome_date::date >= te.cohort_start::date
                 AND oe.outcome_date::date <= ({tar_limit})::date
            THEN 1 ELSE 0
        END AS had_event,
        CASE
            WHEN oe.outcome_date IS NOT NULL
                 AND oe.outcome_date::date >= te.cohort_start::date
                 AND oe.outcome_date::date <= ({tar_limit})::date
            THEN (oe.outcome_date::date - te.cohort_start::date)::float
            ELSE (({tar_limit})::date - te.cohort_start::date)::float
        END AS time_days
        {strata_select}
    FROM target_entry te
    JOIN {schema.t('observation_period')} op
        ON te.person_id = op.person_id
        AND te.cohort_start BETWEEN op.observation_period_start_date AND op.observation_period_end_date
    JOIN {schema.t('person')} p ON te.person_id = p.person_id
    LEFT JOIN {schema.t('concept')} gc ON p.gender_concept_id = gc.concept_id
    LEFT JOIN outcome_entry oe ON te.person_id = oe.person_id
    WHERE te.cohort_start::date < ({tar_limit})::date
)
SELECT person_id, time_days, had_event{strata_out}
FROM survival_data
WHERE time_days > 0
"""


# ── raw SQL (cohort SQL console) ─────────────────────────────────────────

def check_read_only_sql(sql: str) -> str:
    """Validate a user-supplied query is read-only; return it stripped.

    Same guard as the server's ``/api/cohorts/sql/execute``. The CDM session is
    also opened read-only, so this is the second of two locks.
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
    """Execute a validated read-only query, appending a LIMIT when absent."""
    stripped = check_read_only_sql(sql)
    if "LIMIT" not in stripped.upper():
        stripped = f"{stripped}\nLIMIT {int(limit)}"
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
    conditions: list[psysql.Composable] = []
    params: list = []
    accent = has_unaccent(conn)

    def _ilike(column: str) -> str:
        return (
            f"unaccent({column}) ILIKE unaccent(%s)" if accent else f"{column} ILIKE %s"
        )

    q = (q or "").strip()
    if q:
        if q.isdigit():
            conditions.append(
                psysql.SQL(
                    "(c.concept_id = %s OR c.concept_code = %s OR "
                    + _ilike("c.concept_code")
                    + ")"
                )
            )
            params.extend([int(q), q, f"%{q}%"])
        else:
            conditions.append(
                psysql.SQL(
                    "(" + _ilike("c.concept_name") + " OR " + _ilike("c.concept_code") + ")"
                )
            )
            params.extend([f"%{q}%", f"%{q}%"])
    if domain:
        conditions.append(psysql.SQL("c.domain_id = %s"))
        params.append(domain)
    if vocabulary:
        conditions.append(psysql.SQL("c.vocabulary_id = %s"))
        params.append(vocabulary)
    if standard_only:
        conditions.append(psysql.SQL("c.standard_concept = 'S'"))

    where = (
        psysql.SQL("WHERE ") + psysql.SQL(" AND ").join(conditions)
        if conditions
        else psysql.SQL("")
    )
    query = psysql.SQL(
        """
        SELECT c.concept_id, c.concept_name, c.concept_code,
               c.domain_id, c.vocabulary_id, c.concept_class_id,
               c.standard_concept, c.valid_start_date::text AS valid_start_date,
               c.valid_end_date::text AS valid_end_date, c.invalid_reason,
               COUNT(*) OVER() AS total_count
        FROM {schema}.concept c
        {where}
        ORDER BY c.concept_name
        LIMIT %s OFFSET %s
        """
    ).format(schema=_schema_ident(schema, "concept"), where=where)

    with conn.cursor() as cur:
        cur.execute(query, params + [int(limit), int(offset)])
        columns = [desc[0] for desc in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    total = int(rows[0]["total_count"]) if rows else 0
    for row in rows:
        row.pop("total_count", None)
    return {"concepts": rows, "total": total, "limit": limit, "offset": offset}


def concept_details(conn, schema: SchemaMap, concept_id: int) -> dict | None:
    concept = fetch_one(
        conn,
        psysql.SQL(
            """
            SELECT concept_id, concept_name, concept_code, domain_id, vocabulary_id,
                   concept_class_id, standard_concept,
                   valid_start_date::text AS valid_start_date,
                   valid_end_date::text AS valid_end_date, invalid_reason
            FROM {schema}.concept WHERE concept_id = %s
            """
        ).format(schema=_schema_ident(schema, "concept")),
        [int(concept_id)],
    )
    if not concept:
        return None
    relationships = fetch_all(
        conn,
        psysql.SQL(
            """
            SELECT cr.relationship_id,
                   c2.concept_id AS related_concept_id,
                   c2.concept_name AS related_concept_name,
                   c2.vocabulary_id AS related_vocabulary_id,
                   c2.concept_class_id AS related_concept_class_id,
                   c2.standard_concept AS related_standard_concept
            FROM {rel_schema}.concept_relationship cr
            JOIN {schema}.concept c2 ON c2.concept_id = cr.concept_id_2
            WHERE cr.concept_id_1 = %s
              AND (cr.invalid_reason IS NULL)
            ORDER BY cr.relationship_id, c2.concept_name
            LIMIT 200
            """
        ).format(
            rel_schema=_schema_ident(schema, "concept_relationship"),
            schema=_schema_ident(schema, "concept"),
        ),
        [int(concept_id)],
    )
    return {"concept": concept, "relationships": relationships}


def concept_hierarchy(conn, schema: SchemaMap, concept_id: int) -> dict:
    ancestors = fetch_all(
        conn,
        psysql.SQL(
            """
            SELECT ca.ancestor_concept_id AS concept_id, c.concept_name, c.concept_code,
                   c.vocabulary_id, c.concept_class_id, c.standard_concept,
                   ca.min_levels_of_separation, ca.max_levels_of_separation
            FROM {anc_schema}.concept_ancestor ca
            JOIN {schema}.concept c ON c.concept_id = ca.ancestor_concept_id
            WHERE ca.descendant_concept_id = %s AND ca.ancestor_concept_id != %s
            ORDER BY ca.min_levels_of_separation
            LIMIT 100
            """
        ).format(
            anc_schema=_schema_ident(schema, "concept_ancestor"),
            schema=_schema_ident(schema, "concept"),
        ),
        [int(concept_id), int(concept_id)],
    )
    descendants = fetch_all(
        conn,
        psysql.SQL(
            """
            SELECT ca.descendant_concept_id AS concept_id, c.concept_name, c.concept_code,
                   c.vocabulary_id, c.concept_class_id, c.standard_concept,
                   ca.min_levels_of_separation, ca.max_levels_of_separation
            FROM {anc_schema}.concept_ancestor ca
            JOIN {schema}.concept c ON c.concept_id = ca.descendant_concept_id
            WHERE ca.ancestor_concept_id = %s AND ca.descendant_concept_id != %s
            ORDER BY ca.min_levels_of_separation, c.concept_name
            LIMIT 200
            """
        ).format(
            anc_schema=_schema_ident(schema, "concept_ancestor"),
            schema=_schema_ident(schema, "concept"),
        ),
        [int(concept_id), int(concept_id)],
    )
    return {"ancestors": ancestors, "descendants": descendants}


def concept_source_values(conn, schema: SchemaMap, concept_id: int) -> list[dict]:
    """Source values across clinical tables that map to a concept."""
    results: list[dict] = []
    for domain_name in DOMAIN_CONFIG:
        cfg = get_domain_config(conn, schema, domain_name)
        if not cfg or not cfg.get("source_value"):
            continue
        where_parts = [psysql.SQL("{} = %s").format(_ident(cfg["concept_id"]))]
        params: list = [domain_name, int(concept_id)]
        if cfg.get("source_concept_id"):
            where_parts.append(psysql.SQL("{} = %s").format(_ident(cfg["source_concept_id"])))
            params.append(int(concept_id))
        try:
            results.extend(
                fetch_all(
                    conn,
                    psysql.SQL(
                        """
                        SELECT %s AS domain, {source_col} AS source_value,
                               COUNT(*) AS n_records, COUNT(DISTINCT person_id) AS n_persons
                        FROM {schema}.{table}
                        WHERE ({where}) AND {source_col} IS NOT NULL
                        GROUP BY {source_col}
                        ORDER BY COUNT(*) DESC
                        LIMIT 50
                        """
                    ).format(
                        source_col=_ident(cfg["source_value"]),
                        schema=_schema_ident(schema, cfg["table"]),
                        table=_ident(cfg["table"]),
                        where=psysql.SQL(" OR ").join(where_parts),
                    ),
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
        psysql.SQL(
            "SELECT DISTINCT vocabulary_id FROM {schema}.concept "
            "WHERE vocabulary_id IS NOT NULL ORDER BY vocabulary_id"
        ).format(schema=_schema_ident(schema, "concept")),
    )
    return [r["vocabulary_id"] for r in rows]


def list_concept_domains(conn, schema: SchemaMap) -> list[str]:
    rows = fetch_all(
        conn,
        psysql.SQL(
            "SELECT DISTINCT domain_id FROM {schema}.concept "
            "WHERE domain_id IS NOT NULL ORDER BY domain_id"
        ).format(schema=_schema_ident(schema, "concept")),
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
        rows = fetch_all(
            conn,
            psysql.SQL(
                "SELECT DISTINCT descendant_concept_id FROM {schema}.concept_ancestor "
                "WHERE ancestor_concept_id = ANY(%s)"
            ).format(schema=_schema_ident(schema, "concept_ancestor")),
            (expand,),
        )
        all_ids.update(int(r["descendant_concept_id"]) for r in rows)
    return sorted(all_ids)


def concept_counts(conn, schema: SchemaMap, concept_ids: list[int]) -> list[dict]:
    """Record and person counts per domain for a list of concept_ids."""
    if not concept_ids:
        return []
    ids = [int(c) for c in concept_ids]
    counts: list[dict] = []
    for domain_name, cfg in DOMAIN_CONFIG.items():
        try:
            rows = fetch_all(
                conn,
                psysql.SQL(
                    "SELECT COUNT(*) AS n_records, COUNT(DISTINCT {pid}) AS n_persons "
                    "FROM {schema}.{table} WHERE {cid} = ANY(%s)"
                ).format(
                    pid=_ident(cfg["person_id"]),
                    schema=_schema_ident(schema, cfg["table"]),
                    table=_ident(cfg["table"]),
                    cid=_ident(cfg["concept_id"]),
                ),
                (ids,),
            )
        except Exception:
            conn.rollback()
            continue
        if rows and int(rows[0]["n_records"] or 0) > 0:
            counts.append(
                {
                    "domain": domain_name,
                    "n_records": int(rows[0]["n_records"]),
                    "n_persons": int(rows[0]["n_persons"]),
                }
            )
    return counts


# ── mapping ──────────────────────────────────────────────────────────────

def mapping_summary(conn, schema: SchemaMap, domain: str) -> dict:
    """Term- and row-level mapping coverage for a clinical domain."""
    cfg = get_domain_config(conn, schema, domain)
    if not cfg or not cfg.get("source_value"):
        return {}
    row = fetch_one(
        conn,
        psysql.SQL(
            """
            SELECT COUNT(*) AS total_rows,
                   COUNT(CASE WHEN {cid} != 0 THEN 1 END) AS mapped_rows,
                   COUNT(DISTINCT {sv}) AS total_terms,
                   COUNT(DISTINCT CASE WHEN {cid} != 0 THEN {sv} END) AS mapped_terms
            FROM {schema}.{table}
            """
        ).format(
            cid=_ident(cfg["concept_id"]),
            sv=_ident(cfg["source_value"]),
            schema=_schema_ident(schema, cfg["table"]),
            table=_ident(cfg["table"]),
        ),
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
    """Most frequent unmapped source values of a domain (optionally filtered)."""
    cfg = get_domain_config(conn, schema, domain)
    if not cfg or not cfg.get("source_value"):
        return []

    select_parts = [psysql.SQL("{} AS source_value").format(_ident(cfg["source_value"]))]
    group_parts = [_ident(cfg["source_value"])]
    if cfg.get("source_name"):
        select_parts.append(psysql.SQL("MIN({}) AS source_name").format(_ident(cfg["source_name"])))
    if cfg.get("source_atc"):
        select_parts.append(psysql.SQL("MIN({}) AS source_atc").format(_ident(cfg["source_atc"])))
    select_parts.append(psysql.SQL("COUNT(*) AS n_records"))
    select_parts.append(psysql.SQL("COUNT(DISTINCT {}) AS n_persons").format(_ident(cfg["person_id"])))

    wheres = [psysql.SQL("{} = 0").format(_ident(cfg["concept_id"]))]
    params: list = []
    if search:
        like_parts = [psysql.SQL("{} ILIKE %s").format(_ident(cfg["source_value"]))]
        params.append(f"%{search}%")
        if cfg.get("source_name"):
            like_parts.append(psysql.SQL("{} ILIKE %s").format(_ident(cfg["source_name"])))
            params.append(f"%{search}%")
        wheres.append(psysql.SQL("({})").format(psysql.SQL(" OR ").join(like_parts)))

    query = psysql.SQL(
        "SELECT {select} FROM {schema}.{table} WHERE {where} "
        "GROUP BY {group} ORDER BY COUNT(*) DESC LIMIT %s"
    ).format(
        select=psysql.SQL(", ").join(select_parts),
        schema=_schema_ident(schema, cfg["table"]),
        table=_ident(cfg["table"]),
        where=psysql.SQL(" AND ").join(wheres),
        group=psysql.SQL(", ").join(group_parts),
    )
    params.append(int(limit))
    return fetch_all(conn, query, params)


def mappable_domains(conn, schema: SchemaMap) -> list[str]:
    """Clinical domains that exist in this CDM and expose a source value."""
    domains = []
    for domain_name, cfg in DOMAIN_CONFIG.items():
        if not cfg.get("source_value"):
            continue
        if table_exists(conn, schema, cfg["table"]):
            domains.append(domain_name)
    return domains


def table_exists(conn, schema: SchemaMap, table: str) -> bool:
    row = fetch_one(
        conn,
        "SELECT 1 AS ok FROM information_schema.tables "
        "WHERE table_schema = %s AND table_name = %s LIMIT 1",
        (schema.schema_for(table), table),
    )
    return row is not None


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
