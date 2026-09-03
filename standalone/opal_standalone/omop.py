"""Read-only connections to the external OMOP CDM database.

Engine support comes from the repository's dialect layer (``db.dialects``):
PostgreSQL (reference), Oracle and SQL Server. The engine is chosen per CDM with
``db_type`` in the configuration file.

The server keeps a per-CDM connection pool; a standalone app is a single user
driving one query at a time, so it opens a connection per operation and closes
it. The important behaviours are kept: a statement timeout, a session made
read-only where the engine supports it, and a connection object exposing
``.dialect`` — the attribute every ported engine reads to emit engine-correct
SQL.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

from db.dialects import get_dialect
from opal_standalone.config import CdmConnection
from utils.cdm_helper import SchemaMap, build_schema_map

logger = logging.getLogger(__name__)


class StandaloneConnection:
    """A DBAPI connection that also carries its :class:`Dialect`.

    The analysis engines reach for ``conn.dialect``; the server provides it
    through its pooled connection wrapper, the standalone apps through this one.
    Every other attribute is proxied to the underlying driver connection.
    """

    def __init__(self, conn, dialect):
        self._conn = conn
        self._dialect = dialect

    @property
    def dialect(self):
        return self._dialect

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def close(self):
        self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


# Driver each engine needs, and how to install it. PostgreSQL's psycopg2 is a
# base dependency; the others are optional and imported lazily by their dialect.
_DRIVERS = {
    "postgresql": ("psycopg2", "pip install psycopg2-binary"),
    "oracle": ("oracledb", "pip install oracledb"),
    "sqlserver": ("pyodbc", "pip install pyodbc (+ un pilote ODBC système)"),
}


def driver_status(cdm: CdmConnection) -> tuple[bool, str]:
    """``(available, hint)`` for the driver this CDM's engine needs.

    Lets the UI say « installez oracledb » up front instead of surfacing an
    import error from the first query.
    """
    import importlib

    module, hint = _DRIVERS.get(cdm.db_type, (None, ""))
    if not module:
        return True, ""
    try:
        importlib.import_module(module)
        return True, ""
    except Exception:
        return False, hint


def dialect_for(cdm: CdmConnection):
    """The :class:`Dialect` backing this CDM (PostgreSQL by default)."""
    return get_dialect(cdm.db_type)


def schema_map(cdm: CdmConnection) -> SchemaMap:
    """Schema resolver for a CDM, carrying the engine dialect.

    ``build_schema_map`` attaches ``_dialect``: the SQL builders that only
    receive a schema (cohort builder, characterization, incidence) read it from
    there, so a single object carries both the schema layout and the engine.
    """
    return build_schema_map(cdm)


def _apply_read_only(conn, dialect) -> None:
    """Make the session read-only where the engine supports it (best effort).

    PostgreSQL's switch is a session GUC, and ``SET`` is transactional there —
    so it is applied in autocommit mode, otherwise a later ``rollback()`` (the
    engines do roll back on a failed optional query) would silently undo it.
    Oracle's equivalent is transaction-scoped by design. SQL Server has no
    equivalent — there, as everywhere, the real guarantee is a read-only
    database account.
    """
    try:
        if dialect.name == "postgresql":
            previous = conn.autocommit
            conn.autocommit = True
            try:
                with conn.cursor() as cur:
                    cur.execute("SET default_transaction_read_only = on")
            finally:
                conn.autocommit = previous
        elif dialect.name == "oracle":
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
    except Exception:
        logger.warning(
            "Could not force a read-only session on %s — relying on the database "
            "account's privileges.", dialect.name,
        )


def connect(cdm: CdmConnection, *, allow_temp_tables: bool = False):
    """Open a connection to the CDM: read-only, timeout-bounded, dialect-aware.

    ``allow_temp_tables=True`` skips the read-only session for the two analyses
    that need session-scratch tables (characterization and pathways build
    temporary tables and drop them at the end — the server does the same). They
    still never write to the CDM's own tables.
    """
    dialect = dialect_for(cdm)
    conn = dialect.connect(
        cdm.host, cdm.port, cdm.database, cdm.user, cdm.password,
        connect_timeout=10,
        statement_timeout_ms=int(cdm.statement_timeout_ms),
    )
    try:
        dialect.set_statement_timeout(conn, int(cdm.statement_timeout_ms))
    except Exception:
        logger.debug("Statement timeout not applied on %s", dialect.name, exc_info=True)
    if cdm.read_only and not allow_temp_tables:
        _apply_read_only(conn, dialect)
    return StandaloneConnection(conn, dialect)


@contextmanager
def connection(cdm: CdmConnection, *, allow_temp_tables: bool = False):
    """Context manager yielding a CDM connection, always closed afterwards."""
    conn = connect(cdm, allow_temp_tables=allow_temp_tables)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover - best effort
            logger.debug("Failed to close CDM connection", exc_info=True)


def test_connection(cdm: CdmConnection) -> dict:
    """Probe the CDM: engine, schema presence and person count."""
    schema = schema_map(cdm)
    with connection(cdm) as conn:
        dialect = conn.dialect
        tables = len(dialect.list_tables(conn, schema.schema_for("person")))
        persons = None
        try:
            row = fetch_one(
                conn,
                f"SELECT COUNT(*) AS n FROM "
                f"{dialect.quote_ident(schema.schema_for('person'))}.person",
            )
            persons = int(row["n"]) if row else None
        except Exception:
            conn.rollback()
    return {
        "engine": dialect.label,
        "schema": str(schema),
        "tables_in_schema": tables,
        "persons": persons,
    }


def fetch_all(conn, sql: str, params=None) -> list[dict]:
    """Run a SELECT (psycopg2-style ``%s`` placeholders) and return dicts."""
    with conn.dialect.dict_cursor(conn) as cur:
        conn.dialect.execute(cur, sql, params)
        if cur.description is None:
            return []
        return [dict(row) for row in cur.fetchall()]


def fetch_one(conn, sql: str, params=None) -> dict | None:
    rows = fetch_all(conn, sql, params)
    return rows[0] if rows else None


def table_ref(conn_or_dialect, schema: SchemaMap, table: str) -> str:
    """Schema-qualified table reference for engine-neutral SQL strings."""
    from utils.sql_safety import safe_identifier

    dialect = getattr(conn_or_dialect, "dialect", conn_or_dialect)
    name = schema.schema_for(table) if hasattr(schema, "schema_for") else schema
    return f"{dialect.quote_ident(safe_identifier(name))}.{table}"
