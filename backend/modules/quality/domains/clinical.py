"""
Clinical domain analysis helpers — ported from achilles_like/analysis.py.
Handles: Condition, Drug, Measurement, Observation, Procedure, Visit, Device, Death.
"""
from psycopg2 import sql as psysql
from psycopg2.extras import DictCursor

from config import (
    DOMAIN_CONFIG,
    DEFAULT_TOP_UNMAPPED_TERMS,
    DEFAULT_TOP_CONCEPTS,
    DEFAULT_MAX_RECORDS_PER_PERSON,
)
from utils.sql_safety import safe_identifier


def _get_global_stats(cur, schema: str, table: str, person_id: str) -> dict:
    """Total rows and distinct persons for a clinical table (single query)."""
    cur.execute(psysql.SQL(
        "SELECT COUNT(*) AS total_rows, COUNT(DISTINCT {}) AS distinct_persons"
        " FROM {}.{}"
    ).format(
        psysql.Identifier(person_id),
        psysql.Identifier(schema), psysql.Identifier(table),
    ))
    row = cur.fetchone()
    return {
        "total_rows": int(row["total_rows"] or 0),
        "distinct_persons": int(row["distinct_persons"] or 0),
    }


def _get_monthly_counts(cur, schema: str, table: str, date_col: str) -> dict:
    """Monthly record counts."""
    cur.execute(psysql.SQL(
        "SELECT"
        " date_trunc('month', {date_col})::date AS month_start,"
        " COUNT(*) AS n"
        " FROM {schema}.{table}"
        " GROUP BY date_trunc('month', {date_col})"
        " ORDER BY month_start"
    ).format(
        date_col=psysql.Identifier(date_col),
        schema=psysql.Identifier(schema),
        table=psysql.Identifier(table),
    ))
    months, counts = [], []
    for r in cur.fetchall():
        months.append(r["month_start"].isoformat())
        counts.append(int(r["n"]))
    return {"month_start": months, "count": counts}


def _get_records_per_person(cur, schema: str, table: str, person_id: str, max_bin: int) -> dict:
    """Distribution of records per person (values > max_bin bucketed)."""
    cur.execute(psysql.SQL(
        "SELECT cnt AS records_per_person, COUNT(*) AS n_persons"
        " FROM ("
        "   SELECT {person_id}, COUNT(*) AS cnt"
        "   FROM {schema}.{table}"
        "   GROUP BY {person_id}"
        " ) t"
        " GROUP BY cnt"
        " ORDER BY cnt"
    ).format(
        person_id=psysql.Identifier(person_id),
        schema=psysql.Identifier(schema),
        table=psysql.Identifier(table),
    ))
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


def _get_top_concepts(cur, schema: str, table: str, concept_id: str,
                      source_value: str, limit: int) -> list:
    """Top N concepts by record count.

    Uses a LATERAL subquery to cap source_values at 10 per concept,
    avoiding a full STRING_AGG(DISTINCT) over potentially thousands
    of values per concept (P7 fix).
    """
    cur.execute(psysql.SQL(
        "SELECT"
        "  top.concept_id,"
        "  top.concept_name,"
        "  sv.source_value,"
        "  top.n_records,"
        "  top.n_persons"
        " FROM ("
        "  SELECT"
        "    t.{concept_id} AS concept_id,"
        "    c.concept_name,"
        "    COUNT(*) AS n_records,"
        "    COUNT(DISTINCT t.person_id) AS n_persons"
        "  FROM {schema}.{table} t"
        "  JOIN {schema}.{concept_tbl} c ON t.{concept_id} = c.concept_id"
        "  WHERE t.{concept_id} != 0"
        "  GROUP BY t.{concept_id}, c.concept_name"
        "  ORDER BY n_records DESC"
        "  LIMIT %s"
        " ) top"
        " LEFT JOIN LATERAL ("
        "  SELECT STRING_AGG(DISTINCT sub.{source_value}, ', ' ORDER BY sub.{source_value}) AS source_value"
        "  FROM ("
        "    SELECT DISTINCT {source_value}"
        "    FROM {schema}.{table}"
        "    WHERE {concept_id} = top.concept_id"
        "    LIMIT 10"
        "  ) sub"
        " ) sv ON true"
    ).format(
        concept_id=psysql.Identifier(concept_id),
        schema=psysql.Identifier(schema),
        table=psysql.Identifier(table),
        concept_tbl=psysql.Identifier("concept"),
        source_value=psysql.Identifier(source_value),
    ), (limit,))
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


def _get_mapping_stats(cur, schema: str, table: str, source_value: str, concept_id: str,
                       top_unmapped: int, source_name_col: str | None = None) -> dict:
    """Mapping quality statistics: terms, rows, and top unmapped terms.

    Term-level and row-level stats are computed in a single scan (P8 fix).
    """
    cur.execute(psysql.SQL(
        "SELECT"
        " COUNT(*) AS total_rows,"
        " COUNT(CASE WHEN {concept_id} != 0 THEN 1 END) AS mapped_rows,"
        " COUNT(DISTINCT {source_value}) AS total_terms,"
        " COUNT(DISTINCT CASE WHEN {concept_id} != 0 THEN {source_value} END) AS mapped_terms"
        " FROM {schema}.{table}"
    ).format(
        concept_id=psysql.Identifier(concept_id),
        source_value=psysql.Identifier(source_value),
        schema=psysql.Identifier(schema),
        table=psysql.Identifier(table),
    ))
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
        cur.execute(psysql.SQL(
            "SELECT {source_value} AS source_val, MIN({source_name_col}) AS source_name, COUNT(*) AS n"
            " FROM {schema}.{table}"
            " WHERE {concept_id} = 0"
            " GROUP BY {source_value}"
            " ORDER BY n DESC"
            " LIMIT %s"
        ).format(
            source_value=psysql.Identifier(source_value),
            source_name_col=psysql.Identifier(source_name_col),
            schema=psysql.Identifier(schema),
            table=psysql.Identifier(table),
            concept_id=psysql.Identifier(concept_id),
        ), (top_unmapped,))
        top_unmapped_terms = [
            {"source_value": r["source_val"], "source_name": r["source_name"], "count": int(r["n"])}
            for r in cur.fetchall()
        ]
    else:
        cur.execute(psysql.SQL(
            "SELECT {source_value} AS source_val, COUNT(*) AS n"
            " FROM {schema}.{table}"
            " WHERE {concept_id} = 0"
            " GROUP BY {source_value}"
            " ORDER BY n DESC"
            " LIMIT %s"
        ).format(
            source_value=psysql.Identifier(source_value),
            schema=psysql.Identifier(schema),
            table=psysql.Identifier(table),
            concept_id=psysql.Identifier(concept_id),
        ), (top_unmapped,))
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
    schema = safe_identifier(omop_schema)

    res = {
        "domain": domain_name,
        "table": f"{schema}.{table}",
        "achilles_like": {},
        "mapping": {},
    }

    with conn.cursor(cursor_factory=DictCursor) as cur:
        res["achilles_like"]["global"] = _get_global_stats(cur, schema, table, person_id)
        res["achilles_like"]["by_month"] = _get_monthly_counts(cur, schema, table, date_col)
        res["achilles_like"]["records_per_person"] = _get_records_per_person(
            cur, schema, table, person_id, max_bin=max_records_per_person
        )
        res["achilles_like"]["top_concepts"] = _get_top_concepts(
            cur, schema, table, concept_id, source_value, limit=top_concepts
        )
        res["mapping"] = _get_mapping_stats(
            cur, schema, table, source_value, concept_id,
            top_unmapped=top_unmapped, source_name_col=source_name_col
        )

    return res
