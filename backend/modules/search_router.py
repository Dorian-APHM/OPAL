"""
Global Search endpoint.

Searches across concepts, cohorts, and mappings simultaneously.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from psycopg2 import sql as psysql

from db.app_db import get_db
from db.models import Cohort, MappingDecision, SavedQuery
from utils.sql_safety import safe_identifier
from utils.cdm_helper import get_cdm_connection
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
        Cohort.name.ilike(f"%{escaped_term}%")
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
                    from psycopg2.extras import DictCursor
                    with conn.cursor(cursor_factory=DictCursor) as cur:
                        if search_term.isdigit():
                            sql = psysql.SQL("""
                                SELECT concept_id, concept_name, concept_code,
                                       vocabulary_id, domain_id, standard_concept
                                FROM {}.{}
                                WHERE concept_id = %s
                                LIMIT %s
                            """).format(psysql.Identifier(schema), psysql.Identifier('concept'))
                            cur.execute(sql, (int(search_term), limit))
                        else:
                            sql = psysql.SQL("""
                                SELECT concept_id, concept_name, concept_code,
                                       vocabulary_id, domain_id, standard_concept
                                FROM {}.{}
                                WHERE concept_name ILIKE %s OR concept_code ILIKE %s
                                ORDER BY
                                    CASE WHEN standard_concept = 'S' THEN 0 ELSE 1 END,
                                    LENGTH(concept_name)
                                LIMIT %s
                            """).format(psysql.Identifier(schema), psysql.Identifier('concept'))
                            cur.execute(sql, (f"%{escaped_term}%", f"%{escaped_term}%", limit))
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
                            for domain_name, cfg in DOMAIN_CONFIG.items():
                                table = safe_identifier(cfg["table"])
                                source_col = safe_identifier(cfg["source_value"])
                                source_name_col = safe_identifier(cfg["source_name"]) if cfg.get("source_name") else None
                                where_clause = psysql.SQL("t.{} ILIKE %s").format(psysql.Identifier(source_col))
                                query_params = [domain_name, f"%{escaped_term}%"]
                                if source_name_col:
                                    where_clause = psysql.SQL("t.{} ILIKE %s OR t.{} ILIKE %s").format(
                                        psysql.Identifier(source_col), psysql.Identifier(source_name_col)
                                    )
                                    query_params.append(f"%{escaped_term}%")
                                source_name_select = psysql.SQL("t.{}").format(psysql.Identifier(source_name_col)) if source_name_col else psysql.SQL("NULL")
                                source_name_group = psysql.SQL(", t.{}").format(psysql.Identifier(source_name_col)) if source_name_col else psysql.SQL("")
                                union_parts.append(psysql.SQL("""
                                    SELECT %s AS domain,
                                           t.{source_col} AS source_value,
                                           {source_name_select} AS source_name,
                                           COUNT(*) AS n_records
                                    FROM {schema}.{table} t
                                    WHERE {where_clause}
                                    GROUP BY t.{source_col_group}{source_name_group}
                                """).format(
                                    source_col=psysql.Identifier(source_col),
                                    source_name_select=source_name_select,
                                    schema=psysql.Identifier(schema),
                                    table=psysql.Identifier(table),
                                    where_clause=where_clause,
                                    source_col_group=psysql.Identifier(source_col),
                                    source_name_group=source_name_group,
                                ))
                                sv_params.extend(query_params)

                            if union_parts:
                                sv_composed = psysql.SQL(" UNION ALL ").join(union_parts)
                                sv_sql = psysql.SQL("SELECT * FROM ({}) sub ORDER BY n_records DESC LIMIT %s").format(sv_composed)
                                sv_params.append(limit)
                                cur.execute(sv_sql, sv_params)
                                results["source_values"] = [
                                    {
                                        "source_value": r["source_value"],
                                        "source_name": r["source_name"] or "",
                                        "domain": r["domain"],
                                        "n_records": r["n_records"],
                                        "link": "/concepts",
                                    }
                                    for r in cur.fetchall()
                                ]
                        except Exception as e:
                            logger.warning("Source value search failed in global search: %s", e)
                finally:
                    conn.close()
        except Exception as e:
            logger.warning("Concept search failed in global search: %s", e)

    # 3. Search saved queries
    sq_q = db.query(SavedQuery).filter(SavedQuery.name.ilike(f"%{escaped_term}%"))
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
        MappingDecision.source_value.ilike(f"%{escaped_term}%")
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
