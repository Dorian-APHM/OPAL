"""
ATC code -> class-name harvesting (DISPLAY only) for the cohort-LLM RAG.

A Drug concept-set group is keyed by its ATC code. To title the group with its
class name (instead of a random member's product label), we store the name of each
ATC code present in a CDM's Drug source values, read from the CDM's own OMOP
`concept` ATC vocabulary. Names are whatever the CDM loaded (often English) — this
is display only, never embedded or matched, so the language is irrelevant to recall.
"""
import logging

from sqlalchemy import delete

from db.app_db import SessionLocal
from db.models import AtcLabel, SourceValueCache
from utils.sql_safety import safe_identifier

logger = logging.getLogger(__name__)


def populate_atc_labels(cdm_name: str, conn, omop_schema) -> int:
    """Store {ATC code -> class name} for the Drug ATC codes present in a CDM.

    Reads the distinct source_atc cached for the Drug domain (app DB), looks up their
    names in the CDM `concept` (vocabulary_id='ATC'), replaces the AtcLabel rows for
    this CDM. Returns the number written. No-op (0) when no ATC codes / no ATC vocab.
    """
    app_db = SessionLocal()
    try:
        codes = [
            row[0]
            for row in app_db.query(SourceValueCache.source_atc)
            .filter(
                SourceValueCache.cdm_name == cdm_name,
                SourceValueCache.domain == "Drug",
                SourceValueCache.source_atc.isnot(None),
                SourceValueCache.source_atc != "",
            )
            .distinct()
            .all()
        ]
    finally:
        app_db.close()

    codes = sorted({(c or "").strip().upper() for c in codes if c and c.strip()})
    if not codes:
        return 0

    vocab_schema = omop_schema.schema_for("concept") if hasattr(omop_schema, "schema_for") else omop_schema
    vocab_schema = safe_identifier(vocab_schema)

    dialect = conn.dialect
    concept_ref = f"{dialect.quote_ident(vocab_schema)}.{dialect.quote_ident('concept')}"
    code_frag, code_params = dialect.in_list("concept_code", codes)

    rows: list[dict] = []
    with dialect.dict_cursor(conn) as cur:
        dialect.execute(
            cur,
            f"""
            SELECT concept_code, concept_name
            FROM {concept_ref}
            WHERE vocabulary_id = 'ATC' AND {code_frag}
            """,
            code_params,
        )
        for r in cur.fetchall():
            code = (r["concept_code"] or "").strip().upper()
            name = (r["concept_name"] or "").strip()
            if code and name:
                rows.append({"cdm_name": cdm_name, "atc_code": code, "label": name})

    app_db = SessionLocal()
    try:
        app_db.execute(delete(AtcLabel).where(AtcLabel.cdm_name == cdm_name))
        if rows:
            app_db.bulk_insert_mappings(AtcLabel, rows)
        app_db.commit()
    except Exception:
        app_db.rollback()
        raise
    finally:
        app_db.close()

    logger.info("ATC label harvest for CDM %s: %d/%d codes named", cdm_name, len(rows), len(codes))
    return len(rows)
