"""
Source Value Cache — pre-compute distinct source values with counts
from CDM tables into the app DB for instant search.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from config import DOMAIN_CONFIG
from db.app_db import SessionLocal
from db.dialects import get_dialect
from db.models import SourceValueCache, SourceValueCacheStatus
from utils.cdm_helper import get_domain_config
from utils.reference_labels import get_reference_label_map
from utils.sql_safety import safe_identifier

logger = logging.getLogger(__name__)

_BATCH_SIZE = 5000


def populate_domain(
    cdm_name: str,
    domain_name: str,
    conn,
    omop_schema: str,
    progress_callback: Callable | None = None,
) -> int:
    """
    Populate the source_value_cache for a single domain.

    Reads all distinct (source_value, source_name, concept) tuples with counts
    from the CDM, then writes them to the app DB cache table.

    Returns the number of cached rows.
    """
    # Engine dialect backing this CDM (PostgreSQL by default). Owns the
    # non-portable bits below: metadata existence checks, statement-timeout
    # disabling and the batched streaming cursor.
    dialect = getattr(conn, "dialect", None) or get_dialect("postgresql")

    cfg = get_domain_config(conn, omop_schema, domain_name)
    if not cfg or not cfg.get("source_value"):
        return 0

    # Check table exists in the CDM
    table_name = cfg["table"]
    # Resolve the schema that holds the (clinical) domain table and, separately,
    # the schema that holds the vocabulary `concept` table — they may differ.
    clinical_schema = omop_schema.schema_for(table_name) if hasattr(omop_schema, "schema_for") else omop_schema
    vocab_schema = omop_schema.schema_for("concept") if hasattr(omop_schema, "schema_for") else omop_schema
    clinical_schema = safe_identifier(clinical_schema)
    vocab_schema = safe_identifier(vocab_schema)
    if not dialect.table_exists(conn, clinical_schema, table_name):
        logger.info("Table %s.%s not found — skipping domain %s", clinical_schema, table_name, domain_name)
        return 0

    table = safe_identifier(table_name)
    source_col_name = cfg["source_value"]

    # Verify source_value column exists
    if not dialect.column_exists(conn, clinical_schema, table_name, source_col_name):
        logger.info("Column %s.%s.%s not found — skipping domain %s", clinical_schema, table_name, source_col_name, domain_name)
        return 0

    source_col = safe_identifier(source_col_name)
    concept_col = safe_identifier(cfg["concept_id"])
    source_name_col = safe_identifier(cfg["source_name"]) if cfg.get("source_name") else None
    source_atc_col = safe_identifier(cfg["source_atc"]) if cfg.get("source_atc") else None

    # Build the aggregation query
    sn_select = f", t.{source_name_col} AS source_name" if source_name_col else ", NULL AS source_name"
    sn_group = f", t.{source_name_col}" if source_name_col else ""
    atc_select = f", t.{source_atc_col} AS source_atc" if source_atc_col else ", NULL AS source_atc"
    atc_group = f", t.{source_atc_col}" if source_atc_col else ""

    sql = f"""
        SELECT t.{source_col} AS source_value
               {sn_select}
               {atc_select},
               COUNT(*) AS n_records,
               COUNT(DISTINCT t.person_id) AS n_persons,
               t.{concept_col} AS mapped_concept_id,
               c.concept_name AS mapped_concept_name,
               c.vocabulary_id AS mapped_vocabulary_id,
               c.standard_concept AS mapped_standard_concept
        FROM {clinical_schema}.{table} t
        LEFT JOIN {vocab_schema}.concept c ON c.concept_id = t.{concept_col}
        WHERE t.{source_col} IS NOT NULL
        GROUP BY t.{source_col}{sn_group}{atc_group},
                 t.{concept_col}, c.concept_name, c.vocabulary_id, c.standard_concept
    """

    # Big domains (Measurement especially) GROUP-BY-scan the whole clinical table
    # before the first row is returned, which routinely exceeds the default
    # statement_timeout (OMOP_STATEMENT_TIMEOUT_MS, 30 min) and kills the build right
    # on Measurement. Disable the timeout for THIS query. Done per-domain (not once on
    # the connection in the worker) so it cannot be lost to a transaction boundary
    # between domains and is robust regardless of the connection's state.
    dialect.disable_statement_timeout(conn)

    # Streaming cursor: batches rows from the engine instead of materialising the
    # entire GROUP-BY result of a whole clinical table in client memory before the
    # first fetchmany(). On PostgreSQL this is a server-side named cursor.
    cur = dialect.stream_cursor(conn, sql, _BATCH_SIZE)

    app_db = SessionLocal()
    row_count = 0
    try:
        # Delete old cache for this CDM/domain
        app_db.query(SourceValueCache).filter(
            SourceValueCache.cdm_name == cdm_name,
            SourceValueCache.domain == domain_name,
        ).delete(synchronize_session=False)
        app_db.flush()

        batch: list[dict[str, Any]] = []

        while True:
            rows = cur.fetchmany(_BATCH_SIZE)
            if not rows:
                break
            all_svs = []
            for r in rows:
                sv = str(r["source_value"] or "")
                all_svs.append(sv)
                batch.append({
                    "cdm_name": cdm_name,
                    "domain": domain_name,
                    "source_value": sv,
                    "source_name": str(r.get("source_name") or ""),
                    "source_atc": str(r.get("source_atc") or ""),
                    "n_records": r["n_records"],
                    "n_persons": r["n_persons"],
                    "mapped_concept_id": r.get("mapped_concept_id"),
                    "mapped_concept_name": str(r.get("mapped_concept_name") or ""),
                    "mapped_vocabulary_id": str(r.get("mapped_vocabulary_id") or ""),
                    "mapped_standard_concept": r.get("mapped_standard_concept"),
                })
                row_count += 1

            # Overwrite source_name with FR reference codebook labels when available.
            # The FR codebook is authoritative for source_name display — CDM values
            # (e.g. EN translations from Athena) are only kept as fallback.
            ref_labels = get_reference_label_map(app_db, domain_name, all_svs)
            if ref_labels:
                for item in batch:
                    label = ref_labels.get(item["source_value"])
                    if label:
                        item["source_name"] = label

            app_db.bulk_insert_mappings(SourceValueCache, batch)
            app_db.flush()
            batch.clear()
            if progress_callback:
                progress_callback(row_count)

        app_db.commit()
    except Exception:
        app_db.rollback()
        raise
    finally:
        cur.close()
        app_db.close()

    return row_count


def domains_to_populate() -> list[str]:
    """Domains the cache build will process (those with a source_value column).

    Single source of truth so the populate endpoint can pre-seed the per-domain
    status rows (UI shows 0/total upfront) and the worker iterates the same set."""
    return [d for d, cfg in DOMAIN_CONFIG.items() if cfg.get("source_value")]


def populate_all_domains(
    cdm_name: str,
    conn,
    omop_schema: str,
    progress_callback: Callable | None = None,
    cancelled_check: Callable | None = None,
    enable_sapbert: bool = False,
):
    """
    Populate cache for all domains that have source_value.

    progress_callback(domain, status, completed, total, row_count)
    cancelled_check() -> bool
    enable_sapbert: after each domain's cache is built, also build SapBERT
        suggestions for it (opt-in; no-op if the feature is off or the domain
        has no labelled source values). A SapBERT failure is logged and recorded
        per-domain but does not interrupt the cache build.
    """
    domains_with_source = domains_to_populate()
    total = len(domains_with_source)
    completed = 0

    app_db = SessionLocal()
    try:
        for domain_name in domains_with_source:
            if cancelled_check and cancelled_check():
                if progress_callback:
                    progress_callback(domain_name, "cancelled", completed, total, 0)
                break

            # Update status to running
            _upsert_status(app_db, cdm_name, domain_name, "running", started_at=datetime.now(timezone.utc))

            if progress_callback:
                progress_callback(domain_name, "running", completed, total, 0)

            try:
                def _domain_progress(row_count: int):
                    if progress_callback:
                        progress_callback(domain_name, "running", completed, total, row_count)

                row_count = populate_domain(cdm_name, domain_name, conn, omop_schema, _domain_progress)
                completed += 1

                _upsert_status(
                    app_db, cdm_name, domain_name, "done",
                    row_count=row_count,
                    completed_at=datetime.now(timezone.utc),
                )

                if progress_callback:
                    progress_callback(domain_name, "done", completed, total, row_count)

                # Opt-in: build SapBERT suggestions for this domain off the cache
                # we just populated. Isolated from the cache build — its own state
                # row and never fatal to the cache.
                if enable_sapbert and not (cancelled_check and cancelled_check()):
                    try:
                        from modules.mapping.sapbert_build import build_domain_sapbert
                        build_domain_sapbert(cdm_name, domain_name, conn, omop_schema)
                    except Exception:
                        logger.exception(
                            "SapBERT build failed for domain %s / CDM %s", domain_name, cdm_name
                        )

                # Harvest ATC code->class-name (display only) off the Drug cache, so the
                # cohort-LLM RAG can title drug groups with their ATC class instead of a
                # member's product label. Isolated, never fatal to the cache.
                if domain_name == "Drug":
                    try:
                        from modules.concept.atc_labels import populate_atc_labels
                        populate_atc_labels(cdm_name, conn, omop_schema)
                    except Exception:
                        logger.exception("ATC label harvest failed for CDM %s", cdm_name)

            except Exception as e:
                logger.exception("Failed to cache domain %s for CDM %s", domain_name, cdm_name)
                # Reset connection state after error (e.g. cancel)
                try:
                    conn.rollback()
                except Exception:
                    pass
                completed += 1
                _upsert_status(app_db, cdm_name, domain_name, "error", error_message=str(e))
                if progress_callback:
                    progress_callback(domain_name, "error", completed, total, 0)

    finally:
        app_db.close()


def _upsert_status(db, cdm_name: str, domain: str, status: str, **kwargs):
    """Insert or update the cache status for a CDM/domain."""
    existing = db.query(SourceValueCacheStatus).filter(
        SourceValueCacheStatus.cdm_name == cdm_name,
        SourceValueCacheStatus.domain == domain,
    ).first()

    if existing:
        existing.status = status
        for k, v in kwargs.items():
            setattr(existing, k, v)
    else:
        entry = SourceValueCacheStatus(cdm_name=cdm_name, domain=domain, status=status, **kwargs)
        db.add(entry)
    db.commit()
