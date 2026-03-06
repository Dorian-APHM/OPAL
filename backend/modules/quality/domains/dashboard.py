"""
Dashboard domain analysis — ported from achilles_like/analysis.py.
Aggregated overview across all clinical domains.
"""
from psycopg2.extras import DictCursor

from config import DOMAIN_CONFIG


def run_dashboard_analysis(conn, omop_schema: str = "omop_cdm") -> dict:
    """
    Dashboard analysis: summary statistics and mapping quality across all domains.
    """
    person_table = f"{omop_schema}.person"

    res = {
        "domain": "Dashboard",
        "table": "N/A",
        "summary": {},
    }

    with conn.cursor(cursor_factory=DictCursor) as cur:
        # Total persons
        cur.execute(f"SELECT COUNT(*) AS total FROM {person_table}")
        total_persons = int(cur.fetchone()["total"] or 0)

        # Per-domain statistics
        domain_stats = []
        for domain_name, cfg in DOMAIN_CONFIG.items():
            table = cfg["table"]
            person_id = cfg["person_id"]
            concept_id = cfg["concept_id"]
            source_value = cfg["source_value"]
            full_table = f"{omop_schema}.{table}"

            try:
                # Basic stats
                cur.execute(f"""
                    SELECT
                        COUNT(*) AS total_records,
                        COUNT(DISTINCT {person_id}) AS distinct_persons
                    FROM {full_table}
                """)
                row = cur.fetchone()
                total_records = int(row["total_records"] or 0)
                distinct_persons = int(row["distinct_persons"] or 0)
                pct_persons = (distinct_persons / total_persons * 100) if total_persons > 0 else 0

                # Mapping stats
                cur.execute(f"""
                    SELECT
                        COUNT(DISTINCT {source_value}) AS total_terms,
                        COUNT(DISTINCT CASE WHEN {concept_id} != 0 THEN {source_value} END) AS mapped_terms
                    FROM {full_table}
                """)
                row = cur.fetchone()
                total_terms = int(row["total_terms"] or 0)
                mapped_terms = int(row["mapped_terms"] or 0)
                unmapped_terms = total_terms - mapped_terms
                pct_terms_mapped = (mapped_terms / total_terms * 100) if total_terms > 0 else 0

                # Monthly trend (last 12 months) for sparkline
                date_col = cfg.get("date_col")
                sparkline = []
                if date_col:
                    try:
                        cur.execute(f"""
                            SELECT
                                date_trunc('month', {date_col})::date AS m,
                                COUNT(*) AS n
                            FROM {full_table}
                            WHERE {date_col} >= (CURRENT_DATE - INTERVAL '12 months')
                            GROUP BY 1
                            ORDER BY 1
                        """)
                        sparkline = [int(r["n"]) for r in cur.fetchall()]
                    except Exception:
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
            except Exception:
                # Table may not exist — skip silently
                conn.rollback()
                domain_stats.append({
                    "domain": domain_name,
                    "total_records": 0,
                    "distinct_persons": 0,
                    "pct_persons": 0,
                    "total_terms": 0,
                    "mapped_terms": 0,
                    "unmapped_terms": 0,
                    "pct_terms_mapped": 0,
                    "error": "Table not found",
                })

        res["summary"]["total_persons"] = total_persons
        res["summary"]["domains"] = domain_stats

    return res
