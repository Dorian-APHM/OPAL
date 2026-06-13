"""
In-app SapBERT build for one (CDM, domain).

Wired into the Source Value Cache build: once a domain's cache is populated
(source values + enriched labels), this:
  1. reads the **source labels** from the Source Value Cache (rows with a label),
  2. reads the domain's **standard concepts** from the CDM `concept` table,
  3. calls the opal-sapbert runner (/index then /match) to get top-K matches,
  4. writes them into `sapbert_mappings` (per CDM+domain), and tracks progress in
     `sapbert_domain_state`.

The backend owns the CDM connection and the app DB; the runner is pure compute.
A SapBERT failure never breaks the cache build — it is recorded as an error state
for that domain and the cache build continues.
"""
import logging
from datetime import datetime, timezone

from db.app_db import SessionLocal
from db.models import SapbertDomainState, SapbertMapping, SourceValueCache
from modules import sapbert_client
from utils.sql_safety import safe_identifier

logger = logging.getLogger(__name__)

_TARGET_FETCH_SIZE = 10000


def _now():
    return datetime.now(timezone.utc)


def _upsert_domain_state(db, cdm_name: str, domain: str, **kwargs) -> None:
    """Insert/update SapbertDomainState. `enabled` is left untouched unless passed,
    so a rebuild preserves the user's per-domain toggle."""
    existing = (
        db.query(SapbertDomainState)
        .filter(SapbertDomainState.cdm_name == cdm_name, SapbertDomainState.domain == domain)
        .first()
    )
    if existing:
        for k, v in kwargs.items():
            setattr(existing, k, v)
    else:
        db.add(SapbertDomainState(cdm_name=cdm_name, domain=domain, **kwargs))
    db.commit()


def _fetch_source_labels(app_db, cdm_name: str, domain: str) -> list[dict]:
    """Distinct labelled source values for (cdm, domain) from the Source Value Cache."""
    rows = (
        app_db.query(SourceValueCache.source_value, SourceValueCache.source_name)
        .filter(
            SourceValueCache.cdm_name == cdm_name,
            SourceValueCache.domain == domain,
            SourceValueCache.source_name.isnot(None),
            SourceValueCache.source_name != "",
        )
        .distinct()
        .all()
    )
    seen: dict[str, str] = {}
    for code, name in rows:
        if code and name and code not in seen:
            seen[code] = name
    return [{"code": c, "name": n} for c, n in seen.items()]


def _fetch_standard_concepts(conn, schema, domain: str) -> list[dict]:
    """All standard, valid concepts of the domain from the CDM vocabulary `concept`
    (every standard vocabulary of the domain — SNOMED, CPT4, ICD10PCS, …)."""
    vocab_schema = schema.schema_for("concept") if hasattr(schema, "schema_for") else schema
    vocab_schema = safe_identifier(vocab_schema)
    dialect = conn.dialect
    concept_ref = f"{dialect.quote_ident(vocab_schema)}.{dialect.quote_ident('concept')}"
    sql = f"""
        SELECT concept_id, concept_code, concept_name, vocabulary_id
        FROM {concept_ref}
        WHERE domain_id = %s
          AND standard_concept = 'S'
          AND invalid_reason IS NULL
          AND concept_name IS NOT NULL
          AND concept_name <> ''
          AND NOT ({dialect.ilike('concept_name', "'%%(deprecated)%%'")})
    """
    out: list[dict] = []
    cur = dialect.stream_cursor(conn, sql, _TARGET_FETCH_SIZE, (domain,))
    try:
        while True:
            rows = cur.fetchmany(_TARGET_FETCH_SIZE)
            if not rows:
                break
            for r in rows:
                out.append({
                    "concept_id": r["concept_id"],
                    "concept_code": str(r.get("concept_code") or ""),
                    "concept_name": str(r["concept_name"]),
                    "vocabulary_id": str(r.get("vocabulary_id") or ""),
                })
    finally:
        cur.close()
    return out


def build_domain_sapbert(cdm_name: str, domain: str, conn, schema, top_k: int = 5, cancel_check=None) -> int:
    """Build SapBERT mappings for one (cdm, domain). Returns rows written.

    No-op (and no state row) when the feature is off or the domain has no labelled
    source values. `cancel_check` (if given) is polled during indexing to abort
    early. Raises on hard failure after recording an error state.
    """
    if not sapbert_client.is_enabled():
        return 0

    app_db = SessionLocal()
    try:
        sources = _fetch_source_labels(app_db, cdm_name, domain)
        if not sources:
            # Nothing to map for this domain — leave no state row.
            return 0

        _upsert_domain_state(app_db, cdm_name, domain, status="running", error_message=None)

        targets = _fetch_standard_concepts(conn, schema, domain)
        if not targets:
            _upsert_domain_state(
                app_db, cdm_name, domain, status="error",
                row_count=0, error_message=f"no standard concepts for domain {domain}",
            )
            return 0

        key = sapbert_client.targets_key(cdm_name, domain)
        sapbert_client.index_targets(key, targets, cancel_check=cancel_check)
        if cancel_check and cancel_check():
            raise sapbert_client.SapbertCancelled()
        mappings = sapbert_client.match_sources(key, sources, top_k=top_k)

        # Replace this CDM+domain's mappings atomically.
        app_db.query(SapbertMapping).filter(
            SapbertMapping.cdm_name == cdm_name,
            SapbertMapping.domain == domain,
        ).delete(synchronize_session=False)
        rows = [{**m, "cdm_name": cdm_name, "domain": domain} for m in mappings]
        if rows:
            app_db.bulk_insert_mappings(SapbertMapping, rows)
        app_db.commit()

        _upsert_domain_state(
            app_db, cdm_name, domain, status="done",
            row_count=len(rows), built_at=_now(), error_message=None,
        )
        logger.info(
            "SapBERT built %s/%s: %d sources, %d targets -> %d rows",
            cdm_name, domain, len(sources), len(targets), len(rows),
        )
        return len(rows)
    except sapbert_client.SapbertCancelled:
        app_db.rollback()
        _upsert_domain_state(
            app_db, cdm_name, domain, status="cancelled", error_message="Annulé"
        )
        raise
    except Exception as e:
        app_db.rollback()
        _upsert_domain_state(
            app_db, cdm_name, domain, status="error", error_message=str(e)[:500]
        )
        raise
    finally:
        app_db.close()
