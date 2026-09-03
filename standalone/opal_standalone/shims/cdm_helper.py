"""Standalone replacement for ``backend/utils/cdm_helper.py``.

The server version looks CDMs up in the application database and raises FastAPI
exceptions. The standalone apps read their single CDM from a TOML file, so only
the *schema resolution* and *optional column detection* parts are needed. Both
are reproduced here with identical behaviour, minus the app-DB and FastAPI
dependencies.
"""
from __future__ import annotations

import logging
import threading

from config import TABLE_CATEGORY
from utils.sql_safety import safe_identifier

logger = logging.getLogger(__name__)


class SchemaMap(str):
    """A CDM schema reference that resolves the right schema per OMOP table.

    Behaves like the default schema string, and resolves per-category overrides
    through :meth:`schema_for` / :meth:`t` — same contract as the server's
    ``utils.cdm_helper.SchemaMap``.
    """

    def __new__(cls, default_schema: str, category_schemas: dict | None = None):
        default = safe_identifier(default_schema)
        obj = super().__new__(cls, default)
        cats: dict[str, str] = {}
        for category, schema in (category_schemas or {}).items():
            if schema:
                cats[category] = safe_identifier(schema)
        obj._category_schemas = cats
        return obj

    def schema_for(self, table: str) -> str:
        """Validated schema name holding ``table`` (default schema as fallback)."""
        category = TABLE_CATEGORY.get(table)
        if category is not None:
            override = self._category_schemas.get(category)
            if override:
                return override
        return str(self)

    def t(self, table: str) -> str:
        """Fully-qualified ``schema.table`` reference."""
        return f"{self.schema_for(table)}.{table}"


def build_schema_map(cdm, settings=None) -> SchemaMap:
    """Build a :class:`SchemaMap` from anything exposing ``omop_schema``/``schema``.

    Accepts the standalone ``CdmConnection`` as well as any object with
    ``omop_schema`` and ``schema_categories`` attributes. As on the server, the
    CDM's engine dialect is attached to the map (``_dialect``) so the SQL
    builders that only receive a schema still emit engine-correct SQL.
    """
    default = (
        getattr(cdm, "schema", None)
        or getattr(cdm, "omop_schema", None)
        or "omop_cdm"
    )
    categories = dict(getattr(cdm, "schema_categories", None) or {})
    if settings is not None:
        if getattr(settings, "omop_schema", None):
            default = settings.omop_schema
        categories.update(getattr(settings, "schema_categories", None) or {})

    schema_map = SchemaMap(default, categories)
    from db.dialects import get_dialect

    db_type = getattr(cdm, "db_type", None) if cdm is not None else None
    schema_map._dialect = get_dialect(db_type if isinstance(db_type, str) else None)
    return schema_map


_column_exists_cache: dict[tuple[str, str, str, str], bool] = {}
_column_exists_lock = threading.Lock()


def _column_exists(conn, schema: str, table: str, column: str) -> bool:
    """Check whether a column exists in a table (cached), via the CDM's dialect."""
    dsn = conn.dsn if hasattr(conn, "dsn") else str(id(conn))
    cache_key = (dsn, schema, table, column)
    with _column_exists_lock:
        cached = _column_exists_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        # Each engine queries its own metadata catalog (information_schema on
        # PostgreSQL, ALL_TAB_COLUMNS on Oracle, …).
        exists = conn.dialect.column_exists(conn, schema, table, column)
    except Exception:
        # Do not cache failures: a transient error must not permanently disable
        # a column that actually exists.
        logger.warning("Column existence check failed for %s.%s.%s", schema, table, column)
        return False
    with _column_exists_lock:
        _column_exists_cache[cache_key] = exists
    return exists


def get_domain_config(conn, schema: str, domain: str) -> dict:
    """DOMAIN_CONFIG for a domain, minus optional columns absent from this CDM."""
    from config import DOMAIN_CONFIG

    cfg = DOMAIN_CONFIG.get(domain)
    if not cfg:
        return {}
    cfg = dict(cfg)

    optional_cols = ["source_name", "source_concept_id", "source_atc"]
    table = cfg.get("table", "")
    table_schema = schema.schema_for(table) if isinstance(schema, SchemaMap) else schema
    for opt in optional_cols:
        col_name = cfg.get(opt)
        if col_name and not _column_exists(conn, table_schema, table, col_name):
            logger.info(
                "Optional column %s.%s.%s not found — disabling '%s' for domain %s",
                table_schema, table, col_name, opt, domain,
            )
            del cfg[opt]
    return cfg


def get_cdm_connection(*_args, **_kwargs):  # pragma: no cover - not reachable
    raise NotImplementedError(
        "The standalone apps open CDM connections through opal_standalone.omop"
    )


def check_cdm_access(*_args, **_kwargs) -> None:
    """No-op: the standalone apps have no users and no access control."""
    return None


def raise_source_value_cache_missing(cdm_name: str, domain: str | None = None):
    """Server-side signal that the source-value cache is missing.

    The standalone bricks query the CDM directly (there is no app-DB cache), so
    nothing raises this; it exists to keep the module's surface compatible with
    ``backend/utils/cdm_helper.py``.
    """
    raise RuntimeError(
        f"Source value cache is not available in standalone mode (CDM '{cdm_name}', "
        f"domain '{domain}')."
    )
