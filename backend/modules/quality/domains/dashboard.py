"""
Dashboard domain analysis — ported from achilles_like/analysis.py.
Aggregated overview across all clinical domains.
"""
import logging
from psycopg2 import sql as psysql
from psycopg2.extras import DictCursor

logger = logging.getLogger(__name__)

from config import DOMAIN_CONFIG
from utils.sql_safety import safe_identifier
from utils.cdm_helper import get_domain_config


def run_dashboard_analysis(conn, omop_schema: str = "omop_cdm") -> dict:
    """
    Dashboard analysis: summary statistics and mapping quality across all domains.

    Uses a single UNION ALL query to fetch stats for all domains at once,
    then individual sparkline queries only for domains that have a date column.
    """
    schema = safe_identifier(omop_schema)
    _s = psysql.Identifier(schema)
    _person = psysql.Identifier("person")

    res = {
        "domain": "Dashboard",
        "table": "N/A",
        "summary": {},
    }

    with conn.cursor(cursor_factory=DictCursor) as cur:
        # Total persons
        cur.execute(psysql.SQL("SELECT COUNT(*) AS total FROM {}.{}").format(_s, _person))
        total_persons = int(cur.fetchone()["total"] or 0)

        # Build a single UNION ALL query — only for domains whose table exists in the CDM
        union_parts = []
        domain_order = []
        for domain_name in DOMAIN_CONFIG:
            cfg = get_domain_config(conn, schema, domain_name)
            if not cfg:
                continue
            # Check table exists before including in UNION ALL
            table_name = cfg["table"]
            cur.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s LIMIT 1",
                (schema, table_name),
            )
            if not cur.fetchone():
                continue
            table = safe_identifier(cfg["table"])
            person_id = safe_identifier(cfg["person_id"])
            concept_id = safe_identifier(cfg["concept_id"])
            source_value = safe_identifier(cfg["source_value"])
            part = psysql.SQL("""
                SELECT
                    {domain} AS domain,
                    COUNT(*) AS total_records,
                    COUNT(DISTINCT {pid}) AS distinct_persons,
                    COUNT(DISTINCT {sv}) AS total_terms,
                    COUNT(DISTINCT CASE WHEN {cid} != 0 THEN {sv} END) AS mapped_terms
                FROM {schema}.{table}
            """).format(
                domain=psysql.Literal(domain_name),
                pid=psysql.Identifier(person_id),
                sv=psysql.Identifier(source_value),
                cid=psysql.Identifier(concept_id),
                schema=_s,
                table=psysql.Identifier(table),
            )
            union_parts.append(part)
            domain_order.append(domain_name)

        # Execute merged query
        stats_by_domain: dict[str, dict] = {}
        if union_parts:
            try:
                full_query = union_parts[0]
                for part in union_parts[1:]:
                    full_query = psysql.SQL("{} UNION ALL {}").format(full_query, part)
                cur.execute(full_query)
                for row in cur.fetchall():
                    stats_by_domain[row["domain"]] = dict(row)
            except Exception:
                logger.warning("Failed to fetch merged domain stats", exc_info=True)
                conn.rollback()

        # Build results with sparklines (still per-domain, but stats are pre-fetched)
        domain_stats = []
        for domain_name in domain_order:
            row_data = stats_by_domain.get(domain_name)
            if not row_data:
                domain_stats.append({
                    "domain": domain_name, "total_records": 0,
                    "distinct_persons": 0, "pct_persons": 0,
                    "total_terms": 0, "mapped_terms": 0,
                    "unmapped_terms": 0, "pct_terms_mapped": 0,
                    "error": "Table not found",
                })
                continue

            total_records = int(row_data["total_records"] or 0)
            distinct_persons = int(row_data["distinct_persons"] or 0)
            pct_persons = (distinct_persons / total_persons * 100) if total_persons > 0 else 0
            total_terms = int(row_data["total_terms"] or 0)
            mapped_terms = int(row_data["mapped_terms"] or 0)
            unmapped_terms = total_terms - mapped_terms
            pct_terms_mapped = (mapped_terms / total_terms * 100) if total_terms > 0 else 0

            cfg = get_domain_config(conn, schema, domain_name)
            date_col_name = cfg.get("date_col")
            sparkline = []
            if date_col_name:
                table = safe_identifier(cfg["table"])
                date_col_name = safe_identifier(date_col_name)
                _dc = psysql.Identifier(date_col_name)
                try:
                    cur.execute(psysql.SQL("""
                        SELECT date_trunc('month', {dc})::date AS m, COUNT(*) AS n
                        FROM {schema}.{table}
                        WHERE {dc} >= (CURRENT_DATE - INTERVAL '12 months')
                        GROUP BY 1 ORDER BY 1
                    """).format(dc=_dc, schema=_s, table=psysql.Identifier(table)))
                    sparkline = [int(r["n"]) for r in cur.fetchall()]
                except Exception:
                    logger.warning("Failed to fetch sparkline for %s", domain_name, exc_info=True)
                    conn.rollback()

            domain_stats.append({
                "domain": domain_name,
                "total_records": total_records,
                "distinct_persons": distinct_persons,
                "pct_persons": round(pct_persons, 2),
                "total_terms": total_terms,
                "mapped_terms": mapped_terms,
                "unmapped_terms": unmapped_terms,
                "pct_terms_mapped": round(pct_terms_mapped, 2),
                "sparkline": sparkline,
            })

        res["summary"]["total_persons"] = total_persons
        res["summary"]["domains"] = domain_stats

    return res
