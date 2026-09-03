"""
Global Search endpoint.

Searches across concepts, cohorts, and mappings simultaneously.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from db.app_db import get_db
from db.models import Cohort, MappingDecision, SavedQuery
from utils.sql_safety import safe_identifier
from utils.cdm_helper import get_cdm_connection, get_domain_config
from utils.reference_labels import enrich_source_names
from utils.text_search import iaccent_ilike
from config import DOMAIN_CONFIG

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/")
def global_search(
    q: str = Query(..., min_length=1, max_length=500),
    cdm_name: str | None = None,
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """
    Search across multiple entity types:
    - Cohorts (by name/description)
    - Concepts (by name/code, requires CDM)
    - Saved queries (by name)
    - Mapping decisions (by source_value)

    Returns grouped results.
    """
    results = {
        "cohorts": [],
        "concepts": [],
        "source_values": [],
        "saved_queries": [],
        "mappings": [],
    }

    search_term = q.strip()
    escaped_term = search_term.replace('%', '\\%').replace('_', '\\_')

    # 1. Search cohorts
    cohort_q = db.query(Cohort).filter(
        iaccent_ilike(Cohort.name, f"%{escaped_term}%")
    )
    if cdm_name:
        cohort_q = cohort_q.filter(Cohort.cdm_name == cdm_name)
    cohorts = cohort_q.limit(limit).all()
    results["cohorts"] = [
        {
            "id": c.id,
            "name": c.name,
            "cdm_name": c.cdm_name,
            "description": c.description or "",
            "link": "/cohorts",
        }
        for c in cohorts
    ]

    # 2. Search concepts (requires CDM connection)
    if cdm_name:
        try:
            conn, schema = get_cdm_connection(db, cdm_name)
            if conn:
                try:
                    dialect = conn.dialect
                    concept_ref = f"{dialect.quote_ident(safe_identifier(schema.schema_for('concept')))}.concept"
                    lim = dialect.limit_offset(str(int(limit)), '0')
                    with dialect.dict_cursor(conn) as cur:
                        if search_term.isdigit():
                            sql = f"""
                                SELECT concept_id, concept_name, concept_code,
                                       vocabulary_id, domain_id, standard_concept
                                FROM {concept_ref}
                                WHERE concept_id = %s
                                {lim}
                            """
                            dialect.execute(cur, sql, (int(search_term),))
                        else:
                            sql = f"""
                                SELECT concept_id, concept_name, concept_code,
                                       vocabulary_id, domain_id, standard_concept
                                FROM {concept_ref}
                                WHERE {dialect.ilike('concept_name', '%s')}
                                   OR {dialect.ilike('concept_code', '%s')}
                                ORDER BY
                                    CASE WHEN standard_concept = 'S' THEN 0 ELSE 1 END,
                                    {dialect.length('concept_name')}
                                {lim}
                            """
                            dialect.execute(cur, sql, (f"%{escaped_term}%", f"%{escaped_term}%"))
                        results["concepts"] = [
                            {
                                "concept_id": r["concept_id"],
                                "concept_name": r["concept_name"],
                                "concept_code": r["concept_code"],
                                "vocabulary_id": r["vocabulary_id"],
                                "domain_id": r["domain_id"],
                                "standard_concept": r["standard_concept"],
                                "link": "/concepts",
                            }
                            for r in cur.fetchall()
                        ]

                        # 2b. Search source values across clinical tables
                        try:
                            union_parts = []
                            sv_params = []
                            for domain_name in DOMAIN_CONFIG:
                                cfg = get_domain_config(conn, schema, domain_name)
                                if not cfg or not cfg.get("source_value"):
                                    continue
                                table = safe_identifier(cfg["table"])
                                table_ref = f"{dialect.quote_ident(safe_identifier(schema.schema_for(table)))}.{dialect.quote_ident(table)}"
                                source_col = dialect.quote_ident(safe_identifier(cfg["source_value"]))
                                source_name_col = dialect.quote_ident(safe_identifier(cfg["source_name"])) if cfg.get("source_name") else None
                                where_clause = dialect.ilike(f"t.{source_col}", "%s")
                                query_params = [domain_name, f"%{escaped_term}%"]
                                if source_name_col:
                                    where_clause = f"{dialect.ilike(f't.{source_col}', '%s')} OR {dialect.ilike(f't.{source_name_col}', '%s')}"
                                    query_params.append(f"%{escaped_term}%")
                                source_name_select = f"t.{source_name_col}" if source_name_col else "NULL"
                                source_name_group = f", t.{source_name_col}" if source_name_col else ""
                                union_parts.append(f"""
                                    SELECT %s AS domain,
                                           t.{source_col} AS source_value,
                                           {source_name_select} AS source_name,
                                           COUNT(*) AS n_records
                                    FROM {table_ref} t
                                    WHERE {where_clause}
                                    GROUP BY t.{source_col}{source_name_group}
                                """)
                                sv_params.extend(query_params)

                            if union_parts:
                                sv_composed = " UNION ALL ".join(union_parts)
                                sv_sql = f"SELECT * FROM ({sv_composed}) sub ORDER BY n_records DESC {dialect.limit_offset(str(int(limit)), '0')}"
                                dialect.execute(cur, sv_sql, sv_params)
                                sv_results = [
                                    {
                                        "source_value": r["source_value"],
                                        "source_name": r["source_name"] or "",
                                        "domain": r["domain"],
                                        "n_records": r["n_records"],
                                        "link": "/concepts",
                                    }
                                    for r in cur.fetchall()
                                ]
                                # Enrich empty source_names from reference codebooks
                                for d in set(r["domain"] for r in sv_results):
                                    domain_rows = [r for r in sv_results if r["domain"] == d]
                                    enrich_source_names(db, d, domain_rows)
                                results["source_values"] = sv_results
                        except Exception as e:
                            logger.warning("Source value search failed in global search: %s", e)
                finally:
                    conn.close()
        except Exception as e:
            logger.warning("Concept search failed in global search: %s", e)

    # 3. Search saved queries
    sq_q = db.query(SavedQuery).filter(iaccent_ilike(SavedQuery.name, f"%{escaped_term}%"))
    if cdm_name:
        sq_q = sq_q.filter(SavedQuery.cdm_name == cdm_name)
    saved = sq_q.limit(limit).all()
    results["saved_queries"] = [
        {
            "id": s.id,
            "name": s.name,
            "cdm_name": s.cdm_name,
            "description": s.description or "",
            "link": "/cohorts",  # SQL editor is in cohorts tab
        }
        for s in saved
    ]

    # 4. Search mapping decisions
    map_q = db.query(MappingDecision).filter(
        iaccent_ilike(MappingDecision.source_value, f"%{escaped_term}%")
    )
    if cdm_name:
        map_q = map_q.filter(MappingDecision.cdm_name == cdm_name)
    mappings = map_q.limit(limit).all()
    results["mappings"] = [
        {
            "id": m.id,
            "source_value": m.source_value,
            "domain": m.domain,
            "action": m.action,
            "target_concept_name": m.target_concept_name or "",
            "link": "/mapping",
        }
        for m in mappings
    ]

    total = sum(len(v) for v in results.values())
    return {"query": search_term, "total": total, "results": results}
