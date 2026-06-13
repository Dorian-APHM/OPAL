"""CDM database-engine dialects.

Registry mapping ``db_type`` → ``Dialect`` instance. PostgreSQL is the reference
engine and the default for any CDM without an explicit type. Oracle and SQL Server
are best-effort (drivers imported lazily, SQL helpers not yet validated on real
instances).

Public API::

    from db.dialects import get_dialect, SUPPORTED_DB_TYPES, default_port_for

    dialect = get_dialect(cdm.db_type)        # -> Dialect
    port = default_port_for("oracle")          # -> 1521
"""
from __future__ import annotations

from .base import Dialect, DictRowCursor
from .postgres import PostgresDialect
from .oracle import OracleDialect
from .sqlserver import SqlServerDialect

DEFAULT_DB_TYPE = "postgresql"

# Singletons — dialects are stateless.
_DIALECTS: dict[str, Dialect] = {
    PostgresDialect.name: PostgresDialect(),
    OracleDialect.name: OracleDialect(),
    SqlServerDialect.name: SqlServerDialect(),
}

SUPPORTED_DB_TYPES: list[str] = list(_DIALECTS.keys())


def get_dialect(db_type: str | None) -> Dialect:
    """Return the Dialect for ``db_type`` (defaults to PostgreSQL).

    Raises ValueError for an unknown, non-empty db_type so misconfiguration is
    surfaced rather than silently treated as PostgreSQL."""
    if not db_type:
        return _DIALECTS[DEFAULT_DB_TYPE]
    try:
        return _DIALECTS[db_type]
    except KeyError:
        raise ValueError(
            f"Unsupported CDM db_type '{db_type}'. Supported: {', '.join(SUPPORTED_DB_TYPES)}"
        )


def default_port_for(db_type: str | None) -> int:
    return get_dialect(db_type).default_port


def engine_choices() -> list[dict]:
    """UI-friendly list of {value, label, default_port} for the config page."""
    return [
        {"value": d.name, "label": d.label, "default_port": d.default_port}
        for d in _DIALECTS.values()
    ]


__all__ = [
    "Dialect", "DictRowCursor", "get_dialect", "default_port_for",
    "engine_choices", "SUPPORTED_DB_TYPES", "DEFAULT_DB_TYPE",
]
