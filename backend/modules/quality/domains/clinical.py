"""
Clinical domain analysis helpers — ported from achilles_like/analysis.py.
Handles: Condition, Drug, Measurement, Observation, Procedure, Visit, Device, Death.
"""
from config import (
    DOMAIN_CONFIG,
    DEFAULT_TOP_UNMAPPED_TERMS,
    DEFAULT_TOP_CONCEPTS,
    DEFAULT_MAX_RECORDS_PER_PERSON,
)
from utils.sql_safety import safe_identifier


def _tref(dialect, schema, table):
    return f"{dialect.quote_ident(schema)}.{dialect.quote_ident(table)}"


def _get_global_stats(dialect, cur, schema: str, table: str, person_id: str) -> dict:
    """Total rows and distinct persons for a clinical table (single query)."""
    pid = dialect.quote_ident(person_id)
    dialect.execute(cur,
        f"SELECT COUNT(*) AS total_rows, COUNT(DISTINCT {pid}) AS distinct_persons"
        f" FROM {_tref(dialect, schema, table)}")
    row = cur.fetchone()
    return {
        "total_rows": int(row["total_rows"] or 0),
        "distinct_persons": int(row["distinct_persons"] or 0),
    }


def _get_monthly_counts(dialect, cur, schema: str, table: str, date_col: str) -> dict:
    """Monthly record counts."""
    dc = dialect.quote_ident(date_col)
    trunc = dialect.date_trunc('month', dc)
    dialect.execute(cur,
        f"SELECT {dialect.cast(trunc, 'date')} AS month_start,"
        f" COUNT(*) AS n"
        f" FROM {_tref(dialect, schema, table)}"
        f" GROUP BY {trunc}"
        f" ORDER BY month_start")
    months, counts = [], []
    for r in cur.fetchall():
        months.append(r["month_start"].isoformat())
        counts.append(int(r["n"]))
    return {"month_start": months, "count": counts}


def _get_records_per_person(dialect, cur, schema: str, table: str, person_id: str, max_bin: int) -> dict:
    """Distribution of records per person (values > max_bin bucketed)."""
    pid = dialect.quote_ident(person_id)
    dialect.execute(cur,
        f"SELECT cnt AS records_per_person, COUNT(*) AS n_persons"
        f" FROM ("
        f"   SELECT {pid}, COUNT(*) AS cnt"
        f"   FROM {_tref(dialect, schema, table)}"
        f"   GROUP BY {pid}"
        f" ) t"
        f" GROUP BY cnt"
        f" ORDER BY cnt")
    buckets: dict[int, int] = {}
    for r in cur.fetchall():
        x = int(r["records_per_person"])
        n = int(r["n_persons"])
        key = max_bin if x > max_bin else x
        buckets[key] = buckets.get(key, 0) + n

    records_per_person = sorted(buckets.keys())
    n_persons = [buckets[x] for x in records_per_person]
    return {
        "records_per_person": records_per_person,
        "n_persons": n_persons,
        "max_bin": max_bin,
    }


def _get_top_concepts(dialect, cur, schema: str, table: str, concept_id: str,
                      source_value: str, limit: int, concept_schema: str | None = None) -> list:
    """Top N concepts by record count.

    Uses a LATERAL subquery to cap source_values at 10 per concept,
    avoiding a full STRING_AGG(DISTINCT) over potentially thousands
    of values per concept (P7 fix).

    ``concept_schema`` is the schema holding the vocabulary ``concept`` table;
    it defaults to ``schema`` when the vocabulary lives in the same schema.
    """
    if concept_schema is None:
        concept_schema = schema
    cid = dialect.quote_ident(concept_id)
    sv = dialect.quote_ident(source_value)
    tref = _tref(dialect, schema, table)
    cref = f"{dialect.quote_ident(concept_schema)}.{dialect.quote_ident('concept')}"
    # NOTE: LATERAL + STRING_AGG(DISTINCT … ORDER BY) are PostgreSQL/Oracle idioms;
    # on SQL Server this needs CROSS APPLY + STRING_AGG (no DISTINCT). Best-effort.
    dialect.execute(cur,
        f"SELECT top.concept_id, top.concept_name, sv.source_value, top.n_records, top.n_persons"
        f" FROM ("
        f"  SELECT t.{cid} AS concept_id, c.concept_name,"
        f"    COUNT(*) AS n_records, COUNT(DISTINCT t.person_id) AS n_persons"
        f"  FROM {tref} t"
        f"  JOIN {cref} c ON t.{cid} = c.concept_id"
        f"  WHERE t.{cid} != 0"
        f"  GROUP BY t.{cid}, c.concept_name"
        f"  ORDER BY n_records DESC"
        f"  {dialect.limit_offset('%s', '0')}"
        f" ) top"
        f" LEFT JOIN LATERAL ("
        f"  SELECT STRING_AGG(DISTINCT sub.{sv}, ', ' ORDER BY sub.{sv}) AS source_value"
        f"  FROM ("
        f"    SELECT DISTINCT {sv}"
        f"    FROM {tref}"
        f"    WHERE {cid} = top.concept_id"
        f"    {dialect.limit_offset('10', '0')}"
        f"  ) sub"
        f" ) sv ON 1=1",
        (limit,))
    return [
        {
            "concept_id": str(r["concept_id"]) if r["concept_id"] is not None else "",
            "concept_name": r["concept_name"],
            "source_value": str(r["source_value"]) if r["source_value"] is not None else "",
            "n_records": int(r["n_records"]),
            "n_persons": int(r["n_persons"]),
        }
        for r in cur.fetchall()
    ]


def _get_mapping_stats(dialect, cur, schema: str, table: str, source_value: str, concept_id: str,
                       top_unmapped: int, source_name_col: str | None = None) -> dict:
    """Mapping quality statistics: terms, rows, and top unmapped terms.

    Term-level and row-level stats are computed in a single scan (P8 fix).
    """
    cid = dialect.quote_ident(concept_id)
    sv = dialect.quote_ident(source_value)
    tref = _tref(dialect, schema, table)
    dialect.execute(cur,
        f"SELECT"
        f" COUNT(*) AS total_rows,"
        f" COUNT(CASE WHEN {cid} != 0 THEN 1 END) AS mapped_rows,"
        f" COUNT(DISTINCT {sv}) AS total_terms,"
        f" COUNT(DISTINCT CASE WHEN {cid} != 0 THEN {sv} END) AS mapped_terms"
        f" FROM {tref}")
    row = cur.fetchone()
    total_rows = int(row["total_rows"] or 0)
    mapped_rows = int(row["mapped_rows"] or 0)
    unmapped_rows = total_rows - mapped_rows
    pct_rows_mapped = (mapped_rows / total_rows * 100) if total_rows > 0 else None
    total_terms = int(row["total_terms"] or 0)
    mapped_terms = int(row["mapped_terms"] or 0)
    unmapped_terms = total_terms - mapped_terms
    pct_terms_mapped = (mapped_terms / total_terms * 100) if total_terms > 0 else None

    # Top unmapped terms
    if source_name_col:
        snc = dialect.quote_ident(source_name_col)
        dialect.execute(cur,
            f"SELECT {sv} AS source_val, MIN({snc}) AS source_name, COUNT(*) AS n"
            f" FROM {tref}"
            f" WHERE {cid} = 0"
            f" GROUP BY {sv}"
            f" ORDER BY n DESC"
            f" {dialect.limit_offset('%s', '0')}",
            (top_unmapped,))
        top_unmapped_terms = [
            {"source_value": r["source_val"], "source_name": r["source_name"], "count": int(r["n"])}
            for r in cur.fetchall()
        ]
    else:
        dialect.execute(cur,
            f"SELECT {sv} AS source_val, COUNT(*) AS n"
            f" FROM {tref}"
            f" WHERE {cid} = 0"
            f" GROUP BY {sv}"
            f" ORDER BY n DESC"
            f" {dialect.limit_offset('%s', '0')}",
            (top_unmapped,))
        top_unmapped_terms = [
            {"source_value": r["source_val"], "count": int(r["n"])}
            for r in cur.fetchall()
        ]

    return {
        "terms": {
            "total_terms": total_terms,
            "mapped_terms": mapped_terms,
            "unmapped_terms": unmapped_terms,
            "pct_terms_mapped": pct_terms_mapped,
        },
        "rows": {
            "total_rows": total_rows,
            "mapped_rows": mapped_rows,
            "unmapped_rows": unmapped_rows,
            "pct_rows_mapped": pct_rows_mapped,
        },
        "top_unmapped_terms": top_unmapped_terms,
    }


def run_clinical_domain_analysis(
    conn,
    domain_name: str,
    omop_schema: str = "omop_cdm",
    top_unmapped: int = DEFAULT_TOP_UNMAPPED_TERMS,
    top_concepts: int = DEFAULT_TOP_CONCEPTS,
    max_records_per_person: int = DEFAULT_MAX_RECORDS_PER_PERSON,
) -> dict:
    """Run full analysis for a clinical domain (Condition, Drug, etc.)."""
    if domain_name not in DOMAIN_CONFIG:
        raise ValueError(f"Unknown clinical domain: {domain_name}")

    from utils.cdm_helper import get_domain_config
    cfg = get_domain_config(conn, omop_schema, domain_name)
    if not cfg:
        raise ValueError(f"Unknown clinical domain: {domain_name}")
    table = safe_identifier(cfg["table"])
    person_id = safe_identifier(cfg["person_id"])
    date_col = safe_identifier(cfg["date_col"])
    concept_id = safe_identifier(cfg["concept_id"])
    source_value = safe_identifier(cfg["source_value"])
    source_name_col = safe_identifier(cfg["source_name"]) if cfg.get("source_name") else None
    # Resolve the schema that holds this domain's table and, separately, the
    # schema that holds the vocabulary `concept` table (they may differ).
    schema = omop_schema.schema_for(cfg["table"]) if hasattr(omop_schema, "schema_for") else omop_schema
    schema = safe_identifier(schema)
    concept_schema = omop_schema.schema_for("concept") if hasattr(omop_schema, "schema_for") else schema
    concept_schema = safe_identifier(concept_schema)

    res = {
        "domain": domain_name,
        "table": f"{schema}.{table}",
        "achilles_like": {},
        "mapping": {},
    }

    dialect = conn.dialect
    with dialect.dict_cursor(conn) as cur:
        res["achilles_like"]["global"] = _get_global_stats(dialect, cur, schema, table, person_id)
        res["achilles_like"]["by_month"] = _get_monthly_counts(dialect, cur, schema, table, date_col)
        res["achilles_like"]["records_per_person"] = _get_records_per_person(
            dialect, cur, schema, table, person_id, max_bin=max_records_per_person
        )
        res["achilles_like"]["top_concepts"] = _get_top_concepts(
            dialect, cur, schema, table, concept_id, source_value, limit=top_concepts,
            concept_schema=concept_schema,
        )
        res["mapping"] = _get_mapping_stats(
            dialect, cur, schema, table, source_value, concept_id,
            top_unmapped=top_unmapped, source_name_col=source_name_col
        )

    return res
