"""
Centralized CDM connection helper.

Avoids duplicating the CDM lookup + decrypt + connect + schema logic
across 5+ routers.
"""
import logging
import threading

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from db.models import CdmConfig, AnalysisSettings
from db.omop_connector import get_omop_connection
from utils.crypto import decrypt_password
from utils.sql_safety import safe_identifier
from config import DEFAULT_OMOP_SCHEMA, TABLE_CATEGORY


class SchemaMap(str):
    """A CDM schema reference that resolves the right schema per OMOP table.

    Real-world OMOP deployments may store different categories of tables
    (clinical, vocabulary, …) in different PostgreSQL schemas. ``SchemaMap``
    subclasses ``str`` so that, used directly as a string, it behaves exactly
    like the CDM's default schema — preserving the previous single-schema
    behavior everywhere it isn't yet category-aware. Use :meth:`t` to build a
    fully-qualified ``schema.table`` reference for an f-string, or
    :meth:`schema_for` to obtain just the schema name (e.g. to wrap in a
    ``psycopg2.sql.Identifier``).

    Example::

        f"SELECT * FROM {schema.t('concept')}"     # vocab_schema.concept
        psysql.Identifier(schema.schema_for('person'))  # clinical schema
    """

    def __new__(cls, default_schema: str, category_schemas: dict | None = None):
        default = safe_identifier(default_schema)
        obj = super().__new__(cls, default)
        cats: dict[str, str] = {}
        for category, sch in (category_schemas or {}).items():
            if sch:
                cats[category] = safe_identifier(sch)
        obj._category_schemas = cats
        return obj

    def schema_for(self, table: str) -> str:
        """Return the validated schema name that holds ``table``.

        Falls back to the default schema when the table's category has no
        explicit override (or the table is unknown)."""
        category = TABLE_CATEGORY.get(table)
        if category is not None:
            override = self._category_schemas.get(category)
            if override:
                return override
        return str(self)

    def t(self, table: str) -> str:
        """Return the fully-qualified ``schema.table`` reference for ``table``."""
        return f"{self.schema_for(table)}.{table}"


def build_schema_map(cdm: CdmConfig, settings: AnalysisSettings | None = None) -> SchemaMap:
    """Build a :class:`SchemaMap` from a CDM config and its analysis settings.

    The default schema and per-category overrides defined in AnalysisSettings
    take precedence over those on the CdmConfig."""
    default = None
    if settings is not None and getattr(settings, "omop_schema", None):
        default = settings.omop_schema
    if not default:
        default = (cdm.omop_schema if cdm is not None else None) or DEFAULT_OMOP_SCHEMA

    cats: dict[str, str] = {}
    if cdm is not None and getattr(cdm, "schema_categories", None):
        cats.update(cdm.schema_categories)
    if settings is not None and getattr(settings, "schema_categories", None):
        cats.update(settings.schema_categories)
    return SchemaMap(default, cats)


def get_cdm_connection(db: Session, cdm_name: str):
    """
    Look up a CDM by name, decrypt credentials, open a pooled connection,
    and return (connection, schema_map).

    ``schema_map`` is a :class:`SchemaMap` that resolves the right schema for
    each OMOP table category. It behaves like the default schema string when
    used directly.

    Raises HTTPException 404 if CDM not found.
    """
    cdm = db.query(CdmConfig).filter(CdmConfig.name == cdm_name).first()
    if not cdm:
        raise HTTPException(status_code=404, detail=f"CDM '{cdm_name}' not found")
    password = decrypt_password(cdm.db_password_encrypted)
    conn = get_omop_connection(
        cdm.db_host, cdm.db_port, cdm.db_name, cdm.db_user, password,
        db_type=getattr(cdm, "db_type", None) or "postgresql",
    )
    settings = db.query(AnalysisSettings).filter(AnalysisSettings.cdm_name == cdm_name).first()
    schema = build_schema_map(cdm, settings)
    return conn, schema


_logger = logging.getLogger(__name__)

# Cache for column existence checks, keyed on the physical location
# (dsn, schema, table, column). Column existence is a property of the physical
# schema, so the dsn+schema key is correct across CDMs. Guarded by a lock because
# it is read/written from concurrent worker threads.
_column_exists_cache: dict[tuple[str, str, str, str], bool] = {}
_column_exists_lock = threading.Lock()


def _column_exists(conn, schema: str, table: str, column: str) -> bool:
    """Check if a column exists in a table via information_schema (cached)."""
    # Use the CDM connection's dsn as part of the cache key
    dsn = conn.dsn if hasattr(conn, 'dsn') else str(id(conn))
    cache_key = (dsn, schema, table, column)
    with _column_exists_lock:
        cached = _column_exists_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_name = %s LIMIT 1",
            (schema, table, column),
        )
        exists = cur.fetchone() is not None
        cur.close()
    except Exception:
        # Do NOT cache failures: a transient error must not permanently disable
        # a column that actually exists. Return False for this call only.
        _logger.warning("Column existence check failed for %s.%s.%s", schema, table, column)
        return False
    with _column_exists_lock:
        _column_exists_cache[cache_key] = exists
    return exists


def get_domain_config(conn, schema: str, domain: str) -> dict:
    """Return DOMAIN_CONFIG for a domain, stripping optional columns that don't exist in the CDM.

    This ensures columns like 'source_name' (drug_source_name, measurement_source_name)
    that are not part of the standard OMOP CDM spec are only included when actually present.
    """
    from config import DOMAIN_CONFIG
    cfg = DOMAIN_CONFIG.get(domain)
    if not cfg:
        return {}
    cfg = dict(cfg)  # shallow copy to avoid mutating the global

    # Check optional columns that may be absent from certain CDMs
    optional_cols = ["source_name", "source_concept_id", "source_atc"]
    table = cfg.get("table", "")
    # Resolve the schema that actually holds this domain's table (the table may
    # live in a different schema than the default when per-category schemas are
    # configured).
    table_schema = schema.schema_for(table) if isinstance(schema, SchemaMap) else schema
    for opt in optional_cols:
        col_name = cfg.get(opt)
        if col_name and not _column_exists(conn, table_schema, table, col_name):
            _logger.info(
                "Optional column %s.%s.%s not found — disabling '%s' for domain %s",
                table_schema, table, col_name, opt, domain,
            )
            del cfg[opt]

    return cfg


def raise_source_value_cache_missing(cdm_name: str, domain: str | None = None):
    """Raise HTTP 409 signalling the source-value cache has not been built yet.

    The source-value search / explorer endpoints rely *exclusively* on the
    pre-computed ``SourceValueCache`` (stored in the app DB, always PostgreSQL).
    There is deliberately no live-CDM fallback: it keeps these features engine
    agnostic (no PostgreSQL-specific ``unaccent``/``ILIKE`` ever runs against the
    external CDM, which may be Oracle or SQL Server). When the cache is missing,
    the client should prompt the user to build it rather than silently return an
    empty result.
    """
    raise HTTPException(
        status_code=409,
        detail={
            "code": "source_value_cache_missing",
            "message": (
                f"Le cache des valeurs source n'est pas encore construit pour le CDM "
                f"« {cdm_name} ». Lancez la construction du cache avant de rechercher."
            ),
            "cdm_name": cdm_name,
            "domain": domain,
        },
    )


def check_cdm_access(request: Request, cdm_name: str) -> None:
    """
    Verify the current user has access to the given CDM.

    The Keycloak middleware automatically checks CDM access when cdm_name
    appears as a query parameter or in a recognised path segment. However,
    POST endpoints that receive cdm_name inside the JSON request body bypass
    the middleware check. Call this function in those endpoints to enforce
    access control.

    Does nothing when AUTH_ENABLED is false (dev mode).

    Raises HTTPException 403 if access is denied.
    """
    from config import AUTH_ENABLED

    if not AUTH_ENABLED:
        return

    user_info = getattr(request.state, "user", None)
    if not user_info:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Delegate to the same logic the middleware uses
    from auth.keycloak import _check_cdm_access

    if not _check_cdm_access(cdm_name, user_info):
        raise HTTPException(status_code=403, detail=f"Access denied to CDM '{cdm_name}'")
