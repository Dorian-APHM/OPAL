"""
Concept Explorer — browse, search and navigate OMOP vocabulary concepts.
"""
import csv
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from psycopg2.extras import RealDictCursor

from db.app_db import get_db
from db.models import CdmConfig, AnalysisSettings
from db.omop_connector import get_omop_connection
from utils.crypto import decrypt_password
from config import DEFAULT_OMOP_SCHEMA
from utils.sql_safety import safe_identifier

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/concepts", tags=["concepts"])


def _get_omop_schema(db: Session, cdm: CdmConfig) -> str:
    settings = db.query(AnalysisSettings).filter(
        AnalysisSettings.cdm_name == cdm.name
    ).first()
    return settings.omop_schema if settings else cdm.omop_schema or DEFAULT_OMOP_SCHEMA


def _get_conn(db: Session, cdm_name: str):
    cdm = db.query(CdmConfig).filter(CdmConfig.name == cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{cdm_name}' not found")
    password = decrypt_password(cdm.db_password_encrypted)
    schema = safe_identifier(_get_omop_schema(db, cdm))
    try:
        conn = get_omop_connection(cdm.db_host, cdm.db_port, cdm.db_name, cdm.db_user, password)
    except Exception as e:
        logger.exception("Cannot connect to CDM '%s'", cdm_name)
        raise HTTPException(status_code=502, detail="Cannot connect to CDM database")
    return conn, schema


@router.get("/search")
def search_concepts(
    cdm_name: str,
    q: str = "",
    domain: str | None = None,
    vocabulary: str | None = None,
    standard_only: bool = False,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Search concepts by name, code, or ID."""
    conn, schema = _get_conn(db, cdm_name)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            conditions = []
            params = []

            if q:
                q = q.strip()
                # Support searching by concept_id (integer), concept_code, or text
                if q.isdigit():
                    conditions.append(
                        "(c.concept_id = %s OR c.concept_code = %s OR c.concept_code ILIKE %s)"
                    )
                    params.extend([int(q), q, f"%{q}%"])
                else:
                    conditions.append(
                        "(c.concept_name ILIKE %s OR c.concept_code ILIKE %s)"
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

            where = "WHERE " + " AND ".join(conditions) if conditions else ""

            # P22 fix: COUNT(*) OVER() in a single query instead of 2 separate scans
            cur.execute(
                f"""
                SELECT c.concept_id, c.concept_name, c.concept_code,
                       c.domain_id, c.vocabulary_id, c.concept_class_id,
                       c.standard_concept, c.valid_start_date::text, c.valid_end_date::text,
                       c.invalid_reason,
                       COUNT(*) OVER() AS _total_count
                FROM {schema}.concept c
                {where}
                ORDER BY c.concept_name
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = cur.fetchall()
            total = rows[0]["_total_count"] if rows else 0
            concepts = [{k: v for k, v in dict(r).items() if k != "_total_count"} for r in rows]

        return {"concepts": concepts, "total": total, "limit": limit, "offset": offset}
    finally:
        conn.close()


@router.get("/details/{concept_id}")
def get_concept_details(
    concept_id: int,
    cdm_name: str,
    db: Session = Depends(get_db),
):
    """Get full details for a single concept, including relationships and source values."""
    conn, schema = _get_conn(db, cdm_name)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Main concept
            cur.execute(
                f"""
                SELECT c.concept_id, c.concept_name, c.concept_code,
                       c.domain_id, c.vocabulary_id, c.concept_class_id,
                       c.standard_concept, c.valid_start_date::text, c.valid_end_date::text,
                       c.invalid_reason
                FROM {schema}.concept c
                WHERE c.concept_id = %s
                """,
                [concept_id],
            )
            concept = cur.fetchone()
            if not concept:
                raise HTTPException(status_code=404, detail="Concept not found")

            # Relationships (outgoing)
            cur.execute(
                f"""
                SELECT cr.relationship_id,
                       c2.concept_id AS related_concept_id,
                       c2.concept_name AS related_concept_name,
                       c2.vocabulary_id AS related_vocabulary_id,
                       c2.concept_class_id AS related_concept_class_id,
                       c2.standard_concept AS related_standard_concept
                FROM {schema}.concept_relationship cr
                JOIN {schema}.concept c2 ON c2.concept_id = cr.concept_id_2
                WHERE cr.concept_id_1 = %s
                  AND cr.invalid_reason IS NULL
                ORDER BY cr.relationship_id, c2.concept_name
                LIMIT 200
                """,
                [concept_id],
            )
            relationships = [dict(r) for r in cur.fetchall()]

            # Synonyms (if concept_synonym table exists)
            synonyms = []
            try:
                cur.execute(
                    f"""
                    SELECT concept_synonym_name, language_concept_id
                    FROM {schema}.concept_synonym
                    WHERE concept_id = %s
                    ORDER BY concept_synonym_name
                    """,
                    [concept_id],
                )
                synonyms = [dict(r) for r in cur.fetchall()]
            except Exception:
                conn.rollback()

        return {
            "concept": dict(concept),
            "relationships": relationships,
            "synonyms": synonyms,
        }
    finally:
        conn.close()


@router.get("/hierarchy/{concept_id}")
def get_concept_hierarchy(
    concept_id: int,
    cdm_name: str,
    db: Session = Depends(get_db),
):
    """Get ancestors and descendants via concept_ancestor table."""
    conn, schema = _get_conn(db, cdm_name)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Ancestors
            cur.execute(
                f"""
                SELECT ca.ancestor_concept_id AS concept_id,
                       c.concept_name, c.concept_code,
                       c.vocabulary_id, c.concept_class_id,
                       c.standard_concept,
                       ca.min_levels_of_separation, ca.max_levels_of_separation
                FROM {schema}.concept_ancestor ca
                JOIN {schema}.concept c ON c.concept_id = ca.ancestor_concept_id
                WHERE ca.descendant_concept_id = %s
                  AND ca.ancestor_concept_id != %s
                ORDER BY ca.min_levels_of_separation
                LIMIT 100
                """,
                [concept_id, concept_id],
            )
            ancestors = [dict(r) for r in cur.fetchall()]

            # Descendants
            cur.execute(
                f"""
                SELECT ca.descendant_concept_id AS concept_id,
                       c.concept_name, c.concept_code,
                       c.vocabulary_id, c.concept_class_id,
                       c.standard_concept,
                       ca.min_levels_of_separation, ca.max_levels_of_separation
                FROM {schema}.concept_ancestor ca
                JOIN {schema}.concept c ON c.concept_id = ca.descendant_concept_id
                WHERE ca.ancestor_concept_id = %s
                  AND ca.descendant_concept_id != %s
                ORDER BY ca.min_levels_of_separation
                LIMIT 200
                """,
                [concept_id, concept_id],
            )
            descendants = [dict(r) for r in cur.fetchall()]

        return {
            "concept_id": concept_id,
            "ancestors": ancestors,
            "descendants": descendants,
        }
    finally:
        conn.close()


@router.get("/source-values/{concept_id}")
def get_concept_source_values(
    concept_id: int,
    cdm_name: str,
    db: Session = Depends(get_db),
):
    """Find source values across clinical tables that map to this concept."""
    conn, schema = _get_conn(db, cdm_name)

    from config import DOMAIN_CONFIG

    results = []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for domain_name, cfg in DOMAIN_CONFIG.items():
                table = safe_identifier(cfg["table"])
                concept_col = safe_identifier(cfg["concept_id"])
                source_col = safe_identifier(cfg["source_value"])
                source_concept_col = safe_identifier(cfg["source_concept_id"]) if cfg.get("source_concept_id") else None

                # Build WHERE clause: match standard concept_id OR source_concept_id
                where_parts = [f"{concept_col} = %s"]
                params: list = [domain_name, concept_id]
                if source_concept_col:
                    where_parts.append(f"{source_concept_col} = %s")
                    params.append(concept_id)
                where_clause = " OR ".join(where_parts)

                try:
                    cur.execute(
                        f"""
                        SELECT %s AS domain,
                               {source_col} AS source_value,
                               COUNT(*) AS n_records,
                               COUNT(DISTINCT person_id) AS n_persons
                        FROM {schema}.{table}
                        WHERE ({where_clause})
                          AND {source_col} IS NOT NULL
                        GROUP BY {source_col}
                        ORDER BY COUNT(*) DESC
                        LIMIT 50
                        """,
                        params,
                    )
                    rows = cur.fetchall()
                    for r in rows:
                        results.append(dict(r))
                except Exception:
                    conn.rollback()

        return {"concept_id": concept_id, "source_values": results}
    finally:
        conn.close()


@router.get("/search-source-value")
def search_source_value(
    cdm_name: str,
    q: str = "",
    domain: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Search clinical tables by source_value and return mapped standard concepts."""
    if not q:
        return {"results": [], "total": 0, "limit": limit, "offset": offset}

    from config import DOMAIN_CONFIG

    conn, schema = _get_conn(db, cdm_name)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Build a UNION ALL across all relevant domains
            domains_to_search = (
                {domain: DOMAIN_CONFIG[domain]}
                if domain and domain in DOMAIN_CONFIG
                else DOMAIN_CONFIG
            )

            union_parts = []
            params = []
            for domain_name, cfg in domains_to_search.items():
                table = safe_identifier(cfg["table"])
                concept_col = safe_identifier(cfg["concept_id"])
                source_col = safe_identifier(cfg["source_value"])
                source_name_col = safe_identifier(cfg["source_name"]) if cfg.get("source_name") else None
                where_clause = f"t.{source_col} ILIKE %s"
                query_params = [domain_name, f"%{q}%"]
                if source_name_col:
                    where_clause += f" OR t.{source_name_col} ILIKE %s"
                    query_params.append(f"%{q}%")
                source_name_select = f"t.{source_name_col}" if source_name_col else "NULL"
                source_name_group = f", t.{source_name_col}" if source_name_col else ""
                union_parts.append(f"""
                    SELECT %s AS domain,
                           t.{source_col} AS source_value,
                           {source_name_select} AS source_name,
                           COUNT(*) AS n_records,
                           COUNT(DISTINCT t.person_id) AS n_persons,
                           t.{concept_col} AS mapped_concept_id,
                           c.concept_name AS mapped_concept_name,
                           c.vocabulary_id AS mapped_vocabulary_id,
                           c.standard_concept AS mapped_standard_concept
                    FROM {schema}.{table} t
                    LEFT JOIN {schema}.concept c ON c.concept_id = t.{concept_col}
                    WHERE {where_clause}
                    GROUP BY t.{source_col}{source_name_group}, t.{concept_col},
                             c.concept_name, c.vocabulary_id, c.standard_concept
                """)
                params.extend(query_params)

            if not union_parts:
                return {"results": [], "total": 0, "limit": limit, "offset": offset}

            full_query = " UNION ALL ".join(union_parts)

            # Get total count
            cur.execute(f"SELECT COUNT(*) AS cnt FROM ({full_query}) sub", params)
            total = cur.fetchone()["cnt"]

            # Get paginated results
            cur.execute(
                f"""
                SELECT * FROM ({full_query}) sub
                ORDER BY n_records DESC
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            results = [dict(r) for r in cur.fetchall()]

        return {"results": results, "total": total, "limit": limit, "offset": offset}
    except Exception as e:
        logger.exception("Source value search failed")
        conn.rollback()
        return {"results": [], "total": 0, "limit": limit, "offset": offset, "error": "An internal error occurred"}
    finally:
        conn.close()


@router.get("/search-source-value/export")
def export_source_value_search(
    cdm_name: str,
    q: str = "",
    domain: str | None = None,
    db: Session = Depends(get_db),
):
    """Export source value search results as CSV."""
    if not q:
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required")

    from config import DOMAIN_CONFIG

    conn, schema = _get_conn(db, cdm_name)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            domains_to_search = (
                {domain: DOMAIN_CONFIG[domain]}
                if domain and domain in DOMAIN_CONFIG
                else DOMAIN_CONFIG
            )

            union_parts = []
            params = []
            for domain_name, cfg in domains_to_search.items():
                table = safe_identifier(cfg["table"])
                concept_col = safe_identifier(cfg["concept_id"])
                source_col = safe_identifier(cfg["source_value"])
                source_name_col = safe_identifier(cfg["source_name"]) if cfg.get("source_name") else None
                where_clause = f"t.{source_col} ILIKE %s"
                query_params = [domain_name, f"%{q}%"]
                if source_name_col:
                    where_clause += f" OR t.{source_name_col} ILIKE %s"
                    query_params.append(f"%{q}%")
                source_name_select = f"t.{source_name_col}" if source_name_col else "NULL"
                source_name_group = f", t.{source_name_col}" if source_name_col else ""
                union_parts.append(f"""
                    SELECT %s AS domain,
                           t.{source_col} AS source_value,
                           {source_name_select} AS source_name,
                           COUNT(*) AS n_records,
                           COUNT(DISTINCT t.person_id) AS n_persons,
                           t.{concept_col} AS mapped_concept_id,
                           c.concept_name AS mapped_concept_name,
                           c.vocabulary_id AS mapped_vocabulary_id,
                           c.standard_concept AS mapped_standard_concept
                    FROM {schema}.{table} t
                    LEFT JOIN {schema}.concept c ON c.concept_id = t.{concept_col}
                    WHERE {where_clause}
                    GROUP BY t.{source_col}{source_name_group}, t.{concept_col},
                             c.concept_name, c.vocabulary_id, c.standard_concept
                """)
                params.extend(query_params)

            if not union_parts:
                raise HTTPException(status_code=404, detail="No domains to search")

            full_query = " UNION ALL ".join(union_parts)
            cur.execute(
                f"SELECT * FROM ({full_query}) sub ORDER BY n_records DESC",
                params,
            )
            rows = [dict(r) for r in cur.fetchall()]

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["source_value", "domain", "n_records", "n_persons",
                         "mapped_concept_id", "mapped_concept_name",
                         "mapped_vocabulary_id", "mapped_standard_concept"])
        for r in rows:
            writer.writerow([
                r["source_value"], r["domain"], r["n_records"], r["n_persons"],
                r.get("mapped_concept_id", ""), r.get("mapped_concept_name", ""),
                r.get("mapped_vocabulary_id", ""), r.get("mapped_standard_concept", ""),
            ])

        output.seek(0)
        filename = f"source_value_search_{q}_{cdm_name}.csv"
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    finally:
        conn.close()


class ConceptCountsRequest(BaseModel):
    concept_ids: list[int]
    domains: list[str] | None = None  # Optional: limit to specific domains for faster queries


@router.post("/counts")
def get_concept_counts(
    req: ConceptCountsRequest,
    cdm_name: str,
    db: Session = Depends(get_db),
):
    """Get record and person counts for a list of concept_ids across all clinical tables."""
    if not req.concept_ids:
        return {"counts": {}}

    from config import DOMAIN_CONFIG

    conn, schema = _get_conn(db, cdm_name)
    # Limit to 200 concepts max to avoid huge queries
    ids = req.concept_ids[:200]
    counts: dict[int, dict] = {}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Query standard concept_id columns (all indexed → fast)
            for cfg in DOMAIN_CONFIG.values():
                table = safe_identifier(cfg["table"])
                concept_col = safe_identifier(cfg["concept_id"])
                try:
                    cur.execute(
                        f"SELECT {concept_col} AS concept_id, COUNT(*) AS n_records, "
                        f"COUNT(DISTINCT person_id) AS n_persons "
                        f"FROM {schema}.{table} WHERE {concept_col} = ANY(%s) GROUP BY {concept_col}",
                        [ids],
                    )
                    for r in cur.fetchall():
                        cid = r["concept_id"]
                        if cid not in counts:
                            counts[cid] = {"n_records": 0, "n_persons": 0}
                        counts[cid]["n_records"] += r["n_records"]
                        counts[cid]["n_persons"] += r["n_persons"]
                except Exception:
                    conn.rollback()

        return {"counts": counts}
    finally:
        conn.close()


@router.post("/counts/source")
def get_concept_source_counts(
    req: ConceptCountsRequest,
    cdm_name: str,
    db: Session = Depends(get_db),
):
    """Get source_concept_id counts. Pass domains to limit to specific tables (much faster)."""
    if not req.concept_ids:
        return {"counts": {}}

    from config import DOMAIN_CONFIG

    conn, schema = _get_conn(db, cdm_name)
    ids = req.concept_ids[:200]
    counts: dict[int, dict] = {}
    # Filter to requested domains only (if provided)
    domains_to_search = {k: v for k, v in DOMAIN_CONFIG.items() if k in req.domains} if req.domains else DOMAIN_CONFIG
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for cfg in domains_to_search.values():
                table = safe_identifier(cfg["table"])
                source_concept_col = safe_identifier(cfg["source_concept_id"]) if cfg.get("source_concept_id") else None
                if not source_concept_col:
                    continue
                try:
                    cur.execute(
                        f"SELECT {source_concept_col} AS concept_id, COUNT(*) AS n_records, "
                        f"COUNT(DISTINCT person_id) AS n_persons "
                        f"FROM {schema}.{table} WHERE {source_concept_col} = ANY(%s) "
                        f"GROUP BY {source_concept_col}",
                        [ids],
                    )
                    for r in cur.fetchall():
                        cid = r["concept_id"]
                        if cid not in counts:
                            counts[cid] = {"n_source_records": 0, "n_source_persons": 0}
                        counts[cid]["n_source_records"] += r["n_records"]
                        counts[cid]["n_source_persons"] += r["n_persons"]
                except Exception:
                    conn.rollback()

        return {"counts": counts}
    finally:
        conn.close()


@router.get("/domains")
def list_concept_domains(
    cdm_name: str,
    db: Session = Depends(get_db),
):
    """List distinct domain_id values from the concept table."""
    conn, schema = _get_conn(db, cdm_name)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT domain_id, COUNT(*) AS count
                FROM {schema}.concept
                WHERE domain_id IS NOT NULL
                GROUP BY domain_id
                ORDER BY count DESC
                """
            )
            return {"domains": [dict(r) for r in cur.fetchall()]}
    finally:
        conn.close()


@router.get("/vocabularies")
def list_vocabularies(
    cdm_name: str,
    db: Session = Depends(get_db),
):
    """List distinct vocabulary_id values from the concept table."""
    conn, schema = _get_conn(db, cdm_name)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT vocabulary_id, COUNT(*) AS count
                FROM {schema}.concept
                WHERE vocabulary_id IS NOT NULL
                GROUP BY vocabulary_id
                ORDER BY count DESC
                """
            )
            return {"vocabularies": [dict(r) for r in cur.fetchall()]}
    finally:
        conn.close()
