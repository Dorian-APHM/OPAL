"""Database dialect abstraction for external OMOP CDM connections.

PostgreSQL is the reference engine and its behaviour is kept byte-for-byte
identical to the historical code path (same psycopg2 idioms, same SQL). Oracle
and SQL Server are *best-effort*: the drivers are imported lazily and the SQL
fragment helpers below are the documented extension point for migrating the
analytical SQL — they must be validated against real instances.

Each Dialect provides three things:
  1. a connection factory (``connect``) over its DBAPI driver,
  2. a dict-row cursor and session helpers (timeout / reset),
  3. SQL fragment helpers that return engine-correct snippets so query builders
     can stop hard-coding PostgreSQL syntax.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Matches a psycopg2-style ``%s`` placeholder or a ``%%`` literal-percent escape.
_PYFORMAT_PH = re.compile(r"%%|%s")


def translate_pyformat(sql: str, make_placeholder) -> str:
    """Rewrite psycopg2 ``%s`` placeholders to another positional paramstyle.

    ``make_placeholder(index)`` returns the engine placeholder for the 1-based
    positional parameter (e.g. ``":1"`` for Oracle, ``"?"`` for ODBC). ``%%`` is
    un-escaped to a literal ``%``. Order is preserved, so the original positional
    params tuple needs no reordering."""
    counter = {"n": 0}

    def _repl(m):
        if m.group(0) == "%%":
            return "%"
        counter["n"] += 1
        return make_placeholder(counter["n"])

    return _PYFORMAT_PH.sub(_repl, sql)


class DictRowCursor:
    """Proxy cursor that yields rows as dicts keyed by column name.

    psycopg2 has RealDictCursor; oracledb and pyodbc return tuples by default,
    so non-PostgreSQL dialects wrap their native cursor in this proxy to give
    callers the uniform ``row["column"]`` access the codebase expects.
    """

    def __init__(self, cur):
        self._cur = cur

    def __getattr__(self, name):
        return getattr(self._cur, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            self._cur.close()
        except Exception:
            pass
        return False

    def _cols(self):
        return [d[0] for d in (self._cur.description or [])]

    def fetchone(self):
        row = self._cur.fetchone()
        return None if row is None else dict(zip(self._cols(), row))

    def fetchall(self):
        cols = self._cols()
        return [dict(zip(cols, r)) for r in self._cur.fetchall()]

    def fetchmany(self, size=None):
        cols = self._cols()
        rows = self._cur.fetchmany(size) if size is not None else self._cur.fetchmany()
        return [dict(zip(cols, r)) for r in rows]

    def __iter__(self):
        cols = self._cols()
        for r in self._cur:
            yield dict(zip(cols, r))


class Dialect:
    """Base class — see module docstring. Subclasses must set ``name`` and
    ``default_port`` and implement ``connect`` / ``dict_cursor``."""

    name: str = "base"
    label: str = "Base"
    default_port: int = 0
    # Whether the engine exposes a native ``unaccent()`` SQL function. When
    # False, ``unaccent()`` is a no-op pass-through (accent-insensitivity must be
    # handled by the column collation or upstream normalization).
    has_unaccent: bool = False

    # ── connection ──────────────────────────────────────────────────────────
    def connect(self, host, port, dbname, user, password, *, connect_timeout: int = 10, **opts) -> Any:
        """Open a raw DBAPI connection. Raises on failure."""
        raise NotImplementedError

    def dict_cursor(self, conn):
        """Return a cursor whose rows support mapping access (``row["col"]``)."""
        raise NotImplementedError

    # ── session management ──────────────────────────────────────────────────
    def set_statement_timeout(self, conn, ms: int) -> None:
        """Apply a per-session statement timeout (best-effort)."""
        return None

    def reset_session(self, conn, default_timeout_ms: int) -> None:
        """Roll back any open transaction and restore the default statement
        timeout before a pooled connection is handed back to the pool."""
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            self.set_statement_timeout(conn, default_timeout_ms)
        except Exception:
            pass

    # ── metadata / streaming (used by the source-value cache builder) ───────
    def table_exists(self, conn, schema: str, table: str) -> bool:
        """Whether ``schema.table`` exists in the CDM. Identifiers are caller-
        validated (safe_identifier) but passed as *values* to the metadata query."""
        raise NotImplementedError

    def column_exists(self, conn, schema: str, table: str, column: str) -> bool:
        raise NotImplementedError

    def disable_statement_timeout(self, conn) -> None:
        """Remove the per-statement timeout for a long full-table aggregation."""
        return None

    def stream_cursor(self, conn, sql: str, itersize: int):
        """Return a cursor that has executed ``sql`` and streams dict rows in
        batches via ``fetchmany(itersize)``. Caller must ``close()`` it."""
        raise NotImplementedError

    def quote_ident(self, name: str) -> str:
        """Quote a caller-validated identifier for inline SQL. PostgreSQL keeps
        names unquoted (safe_identifier already restricts the charset), so the
        reference engine's SQL is unchanged."""
        return name

    def execute(self, cursor, sql: str, params=None):
        """Execute SQL authored with psycopg2-style ``%s`` placeholders.

        PostgreSQL runs it unchanged. Other engines translate the placeholders to
        their own paramstyle first (positional order preserved). This lets query
        builders keep authoring a single ``%s`` dialect of SQL."""
        cursor.execute(sql, params if params is not None else ())
        return cursor

    # ── SQL fragment helpers (extension point) ──────────────────────────────
    # These return engine-correct SQL strings. PostgreSQL returns its native
    # idioms so migrated builders stay identical to today on PG.
    def unaccent(self, expr: str) -> str:
        """Wrap ``expr`` in an accent-stripping function, or pass through."""
        return expr

    def ilike(self, col_sql: str, param_ph: str) -> str:
        """Case-insensitive (and accent-insensitive when supported) match."""
        raise NotImplementedError

    def cast(self, expr: str, type_name: str) -> str:
        """Cast ``expr`` to a portable type name ('date', 'int', 'numeric', 'text')."""
        raise NotImplementedError

    def current_date(self) -> str:
        raise NotImplementedError

    def interval_days(self, days_expr: str) -> str:
        """An interval of N days, addable/subtractable from a date column."""
        raise NotImplementedError

    def extract_year(self, expr: str) -> str:
        raise NotImplementedError

    def limit_offset(self, limit_ph: str, offset_ph: str) -> str:
        """Trailing pagination clause for ``ORDER BY ... <here>``."""
        raise NotImplementedError
