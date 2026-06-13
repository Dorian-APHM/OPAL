"""
Data Management — Dataset extraction engine.

Given a cohort (person_ids + optional visit_ids) and a selection of
OMOP tables/columns, builds one SQL query per table (no aggregation,
raw data) and produces a relational schema (BDR) for the selected tables.
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


# Standard OMOP tables that can be extracted, with their join semantics
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

# OMOP CDM foreign-key relationships between extractable tables
# Each entry: (source_table, source_column, target_table, target_column)
_OMOP_RELATIONSHIPS = [
    # All clinical tables → person
    ("visit_occurrence", "person_id", "person", "person_id"),
    ("condition_occurrence", "person_id", "person", "person_id"),
    ("drug_exposure", "person_id", "person", "person_id"),
    ("measurement", "person_id", "person", "person_id"),
    ("observation", "person_id", "person", "person_id"),
    ("procedure_occurrence", "person_id", "person", "person_id"),
    ("device_exposure", "person_id", "person", "person_id"),
    ("death", "person_id", "person", "person_id"),
    ("observation_period", "person_id", "person", "person_id"),
    # Clinical tables → visit_occurrence
    ("condition_occurrence", "visit_occurrence_id", "visit_occurrence", "visit_occurrence_id"),
    ("drug_exposure", "visit_occurrence_id", "visit_occurrence", "visit_occurrence_id"),
    ("measurement", "visit_occurrence_id", "visit_occurrence", "visit_occurrence_id"),
    ("observation", "visit_occurrence_id", "visit_occurrence", "visit_occurrence_id"),
    ("procedure_occurrence", "visit_occurrence_id", "visit_occurrence", "visit_occurrence_id"),
    ("device_exposure", "visit_occurrence_id", "visit_occurrence", "visit_occurrence_id"),
]


def get_table_columns(conn, omop_schema: str, table_name: str) -> list[dict]:
    """
    Return the column list for a given OMOP table.
    Each entry: {"column_name": str, "data_type": str}
    """
    schema = omop_schema.schema_for(table_name) if hasattr(omop_schema, "schema_for") else omop_schema
    schema = _safe(schema)
    table = _safe(table_name)
    return conn.dialect.list_columns(conn, schema, table)


def list_available_tables(conn, omop_schema: str) -> list[str]:
    """Return OMOP tables that actually exist in the schema.

    All extractable tables belong to the clinical category, so they share one
    schema; resolve it from a representative clinical table."""
    schema = omop_schema.schema_for("person") if hasattr(omop_schema, "schema_for") else omop_schema
    schema = _safe(schema)
    existing = conn.dialect.list_tables(conn, schema)
    return sorted(t for t in EXTRACTABLE_TABLES if t in existing)


def build_table_sql(
    cohort_sql: str,
    omop_schema: str,
    table_name: str,
    columns: list[str],
    same_visit_only: bool,
    cohort_has_visit: bool,
) -> str:
    """
    Build SQL to extract raw (non-aggregated) rows for a single table,
    filtered to cohort patients/visits.

    Returns one row per actual row in the source table (no grouping).
    """
    schema = omop_schema.schema_for(table_name) if hasattr(omop_schema, "schema_for") else omop_schema
    schema = _safe(schema)
    tbl = _safe(table_name)
    meta = EXTRACTABLE_TABLES.get(table_name)
    if not meta:
        raise ValueError(f"Unknown table: {table_name}")

    # Validate columns
    for col in columns:
        _safe(col)

    select_cols = ", ".join(f"t.{_safe(c)}" for c in columns)

    use_visit_filter = same_visit_only and cohort_has_visit

    if table_name == "person":
        # person: 1 row per person, join on person_id only
        return (
            f"WITH cohort AS (\n{cohort_sql}\n)\n"
            f"SELECT {select_cols}\n"
            f"FROM {schema}.{tbl} t\n"
            f"WHERE t.person_id IN (SELECT DISTINCT person_id FROM cohort)\n"
            f"ORDER BY t.person_id"
        )

    if not meta.get("has_visit"):
        # death, observation_period: join on person_id
        return (
            f"WITH cohort AS (\n{cohort_sql}\n)\n"
            f"SELECT {select_cols}\n"
            f"FROM {schema}.{tbl} t\n"
            f"WHERE t.person_id IN (SELECT DISTINCT person_id FROM cohort)\n"
            f"ORDER BY t.person_id"
        )

    # Clinical tables with visit: filter by cohort person_ids
    # and optionally by specific visit_occurrence_ids
    visit_col = _safe(meta.get("visit_col", "visit_occurrence_id"))

    if use_visit_filter:
        return (
            f"WITH cohort AS (\n{cohort_sql}\n)\n"
            f"SELECT {select_cols}\n"
            f"FROM {schema}.{tbl} t\n"
            f"WHERE (t.person_id, t.{visit_col}) IN (\n"
            f"  SELECT DISTINCT person_id, visit_occurrence_id FROM cohort\n"
            f"  WHERE visit_occurrence_id IS NOT NULL\n"
            f")\n"
            f"ORDER BY t.person_id, t.{visit_col}"
        )
    else:
        return (
            f"WITH cohort AS (\n{cohort_sql}\n)\n"
            f"SELECT {select_cols}\n"
            f"FROM {schema}.{tbl} t\n"
            f"WHERE t.person_id IN (SELECT DISTINCT person_id FROM cohort)\n"
            f"ORDER BY t.person_id, t.{visit_col}"
        )


def build_schema(
    table_selections: list[dict],
    all_columns: dict[str, list[dict]] | None = None,
) -> dict:
    """
    Build a BDR (relational schema) description for the selected tables.

    Parameters
    ----------
    table_selections : list[dict]
        Each dict: {"table": str, "columns": list[str]}
    all_columns : dict[str, list[dict]] | None
        Optional mapping table_name → full column list with data_type.
        If provided, includes data_type in the schema.

    Returns
    -------
    dict with keys:
        "tables": list of {name, columns: [{name, data_type?, selected}], pk}
        "relationships": list of {from_table, from_column, to_table, to_column}
    """
    selected_tables = {sel["table"] for sel in table_selections}
    selected_cols_map = {sel["table"]: set(sel["columns"]) for sel in table_selections}

    tables_out = []
    for sel in table_selections:
        tbl = sel["table"]
        meta = EXTRACTABLE_TABLES.get(tbl, {})

        # Determine primary key
        if tbl == "person":
            pk = "person_id"
        elif tbl == "visit_occurrence":
            pk = "visit_occurrence_id"
        elif meta.get("has_visit"):
            pk = f"{tbl}_id"
        else:
            pk = f"{tbl.split('_')[0]}_id" if tbl != "death" else "person_id"

        # Build column list
        cols_out = []
        if all_columns and tbl in all_columns:
            for c in all_columns[tbl]:
                cols_out.append({
                    "name": c["column_name"],
                    "data_type": c["data_type"],
                    "selected": c["column_name"] in selected_cols_map.get(tbl, set()),
                })
        else:
            for col_name in sel["columns"]:
                cols_out.append({
                    "name": col_name,
                    "selected": True,
                })

        tables_out.append({
            "name": tbl,
            "columns": cols_out,
            "pk": pk,
        })

    # Build set of all columns that actually exist per table
    # (from all_columns if available, otherwise from selected columns)
    existing_cols_map: dict[str, set[str]] = {}
    for tbl in selected_tables:
        if all_columns and tbl in all_columns:
            existing_cols_map[tbl] = {c["column_name"] for c in all_columns[tbl]}
        else:
            existing_cols_map[tbl] = selected_cols_map.get(tbl, set())

    # Build relationships between all selected tables that share join columns.
    # Two tables are linked if they both have a common join column
    # (person_id or visit_occurrence_id).
    rels_out = []
    seen = set()  # avoid duplicate (tblA, col, tblB, col) pairs
    join_columns = ["person_id", "visit_occurrence_id"]

    table_list = sorted(selected_tables)
    for i, tbl_a in enumerate(table_list):
        for tbl_b in table_list[i + 1:]:
            for jcol in join_columns:
                if (jcol in existing_cols_map.get(tbl_a, set())
                        and jcol in existing_cols_map.get(tbl_b, set())):
                    key = (tbl_a, jcol, tbl_b, jcol)
                    if key not in seen:
                        seen.add(key)
                        rels_out.append({
                            "from_table": tbl_a,
                            "from_column": jcol,
                            "to_table": tbl_b,
                            "to_column": jcol,
                        })

    return {
        "tables": tables_out,
        "relationships": rels_out,
    }
