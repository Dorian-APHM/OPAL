"""
Data Management — Dataset extraction engine.

Given a cohort (person_ids + optional visit_ids) and a selection of
OMOP tables/columns, builds SQL to produce a flat dataset.

Two modes:
- same_visit_only=True  (requires cohort with sameVisit): one row per
  (person_id, visit_occurrence_id) from the cohort, joined to selected tables
  on both person_id AND visit_occurrence_id.
- same_visit_only=False: one row per (person_id, visit_occurrence_id) for ALL
  visits of each person_id in the cohort.
"""
import logging
import re

logger = logging.getLogger(__name__)

_SAFE_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe(name: str) -> str:
    """Validate SQL identifier."""
    if not _SAFE_ID_RE.match(name):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


# Standard OMOP tables that can be extracted, with their join column to visit
EXTRACTABLE_TABLES = {
    "person": {
        "join_key": "person_id",
        "has_visit": False,
    },
    "visit_occurrence": {
        "join_key": "person_id",
        "visit_col": "visit_occurrence_id",
        "has_visit": True,
    },
    "condition_occurrence": {
        "join_key": "person_id",
        "visit_col": "visit_occurrence_id",
        "has_visit": True,
    },
    "drug_exposure": {
        "join_key": "person_id",
        "visit_col": "visit_occurrence_id",
        "has_visit": True,
    },
    "measurement": {
        "join_key": "person_id",
        "visit_col": "visit_occurrence_id",
        "has_visit": True,
    },
    "observation": {
        "join_key": "person_id",
        "visit_col": "visit_occurrence_id",
        "has_visit": True,
    },
    "procedure_occurrence": {
        "join_key": "person_id",
        "visit_col": "visit_occurrence_id",
        "has_visit": True,
    },
    "device_exposure": {
        "join_key": "person_id",
        "visit_col": "visit_occurrence_id",
        "has_visit": True,
    },
    "death": {
        "join_key": "person_id",
        "has_visit": False,
    },
    "observation_period": {
        "join_key": "person_id",
        "has_visit": False,
    },
}


def get_table_columns(conn, omop_schema: str, table_name: str) -> list[dict]:
    """
    Return the column list for a given OMOP table.
    Each entry: {"column_name": str, "data_type": str}
    """
    schema = _safe(omop_schema)
    table = _safe(table_name)

    sql = """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """
    from psycopg2.extras import DictCursor
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute(sql, (schema, table))
        return [{"column_name": r["column_name"], "data_type": r["data_type"]} for r in cur.fetchall()]


def list_available_tables(conn, omop_schema: str) -> list[str]:
    """Return OMOP tables that actually exist in the schema."""
    schema = _safe(omop_schema)
    sql = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """
    from psycopg2.extras import DictCursor
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute(sql, (schema,))
        existing = {r["table_name"] for r in cur.fetchall()}
    return sorted(t for t in EXTRACTABLE_TABLES if t in existing)


def _agg_expr(col: str, data_type: str | None = None) -> str:
    """Return a PostgreSQL aggregation expression for a column.

    - concept_id columns → comma-separated distinct integers
    - date/datetime columns → min..max range
    - numeric columns → comma-separated distinct values
    - text columns → comma-separated distinct values (truncated)
    """
    safe_col = _safe(col)
    # All columns: aggregate distinct values with string_agg
    return f"string_agg(DISTINCT {safe_col}::text, ', ' ORDER BY {safe_col}::text)"


def build_extraction_sql(
    cohort_sql: str,
    omop_schema: str,
    table_selections: list[dict],
    same_visit_only: bool,
    cohort_has_visit: bool,
) -> str:
    """
    Build the flat extraction SQL.

    Clinical tables with has_visit=True are pre-aggregated per
    (person_id, visit_occurrence_id) to avoid cross-product explosions
    when multiple tables are selected. Each column becomes a
    comma-separated list of distinct values for that visit.

    Parameters
    ----------
    cohort_sql : str
        SQL that produces person_id (and visit_occurrence_id if cohort has sameVisit).
    omop_schema : str
        OMOP schema name.
    table_selections : list[dict]
        Each dict: {"table": str, "columns": list[str]}
    same_visit_only : bool
        If True and cohort has visit IDs, filter by (person_id, visit_occurrence_id) pairs.
    cohort_has_visit : bool
        Whether the cohort SQL produces visit_occurrence_id column.

    Returns
    -------
    str
        SQL query producing the flat dataset.
    """
    schema = _safe(omop_schema)

    if not table_selections:
        raise ValueError("No tables selected for extraction")

    # Validate all identifiers upfront
    for sel in table_selections:
        _safe(sel["table"])
        for col in sel["columns"]:
            _safe(col)

    use_visit_filter = same_visit_only and cohort_has_visit

    # Build CTE for cohort
    parts = [f"WITH cohort AS (\n{cohort_sql}\n)"]

    # Base: start from cohort person_ids joined to visit_occurrence
    # to get one row per (person_id, visit_occurrence_id)
    if use_visit_filter:
        base_sql = (
            "base AS (\n"
            "  SELECT DISTINCT c.person_id, c.visit_occurrence_id\n"
            "  FROM cohort c\n"
            "  WHERE c.visit_occurrence_id IS NOT NULL\n"
            ")"
        )
    else:
        base_sql = (
            "base AS (\n"
            f"  SELECT DISTINCT c.person_id, v.visit_occurrence_id\n"
            f"  FROM cohort c\n"
            f"  JOIN {schema}.visit_occurrence v ON v.person_id = c.person_id\n"
            ")"
        )
    parts.append(base_sql)

    # Separate tables into categories:
    # - clinical (has_visit=True, not visit_occurrence): pre-aggregate per visit
    # - person, visit_occurrence, death, observation_period: 1:1 join, no aggregation needed
    clinical_sels = []
    direct_sels = []

    for sel in table_selections:
        tbl = sel["table"]
        meta = EXTRACTABLE_TABLES.get(tbl)
        if not meta:
            continue
        if meta.get("has_visit") and tbl not in ("visit_occurrence",):
            clinical_sels.append(sel)
        else:
            direct_sels.append(sel)

    # Build pre-aggregated CTEs for clinical tables
    cte_idx = 0
    cte_aliases = {}  # tbl -> cte_alias

    for sel in clinical_sels:
        tbl = sel["table"]
        columns = sel["columns"]
        meta = EXTRACTABLE_TABLES[tbl]
        visit_col = meta.get("visit_col", "visit_occurrence_id")
        cte_alias = f"agg_{tbl}"
        cte_aliases[tbl] = cte_alias

        # Build aggregated columns (skip join keys)
        agg_cols = []
        for col in columns:
            if col == "person_id" or col == visit_col:
                continue
            safe_col = _safe(col)
            agg_cols.append(
                f"  {_agg_expr(col)} AS {_safe(tbl)}__{safe_col}"
            )

        if not agg_cols:
            # Only join keys selected, add a count
            agg_cols.append(f"  COUNT(*) AS {_safe(tbl)}__count")

        agg_select = ",\n".join(agg_cols)
        cte_sql = (
            f"{cte_alias} AS (\n"
            f"  SELECT person_id, {_safe(visit_col)} AS visit_occurrence_id,\n"
            f"{agg_select}\n"
            f"  FROM {schema}.{_safe(tbl)}\n"
            f"  WHERE (person_id, {_safe(visit_col)}) IN (SELECT person_id, visit_occurrence_id FROM base)\n"
            f"  GROUP BY person_id, {_safe(visit_col)}\n"
            f")"
        )
        parts.append(cte_sql)
        cte_idx += 1

    # Build final SELECT
    select_cols = ["b.person_id", "b.visit_occurrence_id"]
    joins = []
    join_idx = 0

    # Direct (non-aggregated) tables
    for sel in direct_sels:
        tbl = sel["table"]
        columns = sel["columns"]
        meta = EXTRACTABLE_TABLES[tbl]
        alias = f"t{join_idx}"
        join_idx += 1

        for col in columns:
            if tbl == "visit_occurrence" and col == "visit_occurrence_id":
                continue
            if col == "person_id":
                continue
            select_cols.append(f"{alias}.{_safe(col)} AS {_safe(tbl)}__{_safe(col)}")

        if tbl == "person":
            joins.append(
                f"LEFT JOIN {schema}.{tbl} {alias} ON {alias}.person_id = b.person_id"
            )
        elif tbl == "visit_occurrence":
            joins.append(
                f"LEFT JOIN {schema}.{tbl} {alias} "
                f"ON {alias}.visit_occurrence_id = b.visit_occurrence_id"
            )
        else:
            # death, observation_period
            joins.append(
                f"LEFT JOIN {schema}.{tbl} {alias} ON {alias}.person_id = b.person_id"
            )

    # Aggregated clinical tables — join from pre-aggregated CTEs
    for sel in clinical_sels:
        tbl = sel["table"]
        columns = sel["columns"]
        meta = EXTRACTABLE_TABLES[tbl]
        cte_alias = cte_aliases[tbl]
        alias = f"t{join_idx}"
        join_idx += 1

        # Add columns from the CTE
        has_data_cols = False
        for col in columns:
            if col == "person_id" or col == meta.get("visit_col", "visit_occurrence_id"):
                continue
            select_cols.append(f"{alias}.{_safe(tbl)}__{_safe(col)}")
            has_data_cols = True

        if not has_data_cols:
            select_cols.append(f"{alias}.{_safe(tbl)}__count")

        joins.append(
            f"LEFT JOIN {cte_alias} {alias} "
            f"ON {alias}.person_id = b.person_id "
            f"AND {alias}.visit_occurrence_id = b.visit_occurrence_id"
        )

    select_clause = ",\n  ".join(select_cols)
    join_clause = "\n".join(joins)

    final_sql = (
        ",\n".join(parts)
        + f"\nSELECT\n  {select_clause}\n"
        + "FROM base b\n"
        + join_clause
        + "\nORDER BY b.person_id, b.visit_occurrence_id"
    )

    return final_sql
