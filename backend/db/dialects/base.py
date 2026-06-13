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
from typing import Any

logger = logging.getLogger(__name__)


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
