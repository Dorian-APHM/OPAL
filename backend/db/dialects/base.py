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
# Matches a psycopg2 *named* placeholder ``%(name)s``.
_NAMED_PH = re.compile(r"%\((\w+)\)s")


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


def translate_named_to_positional(sql: str, params: dict, make_placeholder):
    """Rewrite psycopg2 *named* ``%(name)s`` placeholders to a positional style.

    Returns ``(translated_sql, ordered_params)`` where ``ordered_params`` lists the
    dict values in placeholder order — for drivers (pyodbc) that only support the
    ``?`` qmark style. ``make_placeholder(index)`` returns the engine placeholder."""
    ordered: list = []

    def _repl(m):
        ordered.append(params[m.group(1)])
        return make_placeholder(len(ordered))

    translated = _NAMED_PH.sub(_repl, sql).replace("%%", "%")
    return translated, ordered


def translate_named(sql: str, make_placeholder) -> str:
    """Rewrite ``%(name)s`` placeholders to a *named* style (e.g. Oracle ``:name``),
    keeping a dict bind. ``make_placeholder(name)`` returns the engine placeholder."""
    return _NAMED_PH.sub(lambda m: make_placeholder(m.group(1)), sql).replace("%%", "%")


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

    def list_columns(self, conn, schema: str, table: str) -> list:
        """``[{"column_name", "data_type"}, ...]`` for a table, in ordinal order."""
        raise NotImplementedError

    def list_tables(self, conn, schema: str) -> set:
        """Set of base-table names in a schema."""
        raise NotImplementedError

    def disable_statement_timeout(self, conn) -> None:
        """Remove the per-statement timeout for a long full-table aggregation."""
        return None

    def stream_cursor(self, conn, sql: str, itersize: int, params=None):
        """Return a cursor that has executed ``sql`` and streams dict rows in
        batches via ``fetchmany(itersize)``. Caller must ``close()`` it."""
        raise NotImplementedError

    def quote_ident(self, name: str) -> str:
        """Quote a caller-validated identifier for inline SQL. PostgreSQL keeps
        names unquoted (safe_identifier already restricts the charset), so the
        reference engine's SQL is unchanged."""
        return name

    # ── scratch-table DDL (used by pathways / characterization) ─────────────
    def drop_table_if_exists(self, name: str) -> str:
        return f"DROP TABLE IF EXISTS {name}"

    def create_table_as(self, name: str, select_sql: str) -> str:
        """``CREATE TABLE name AS <select>``. SQL Server uses ``SELECT … INTO``."""
        return f"CREATE TABLE {name} AS {select_sql}"

    def create_temp_table_as(self, name: str, select_sql: str) -> str:
        """Session-scratch table from a SELECT. PostgreSQL uses ``CREATE TEMP
        TABLE``; other engines fall back to a regular table (best-effort — loses
        session isolation but works since callers drop it each run)."""
        return f"CREATE TEMP TABLE {name} AS {select_sql}"

    def create_temp_table(self, name: str, column_defs: str) -> str:
        """Empty session-scratch table with explicit columns."""
        return f"CREATE TEMP TABLE {name} ({column_defs})"

    def analyze_table(self, name: str):
        """SQL to refresh planner stats, or ``None`` if not applicable (it's only
        a performance hint; callers skip when None)."""
        return f"ANALYZE {name}"

    def create_index(self, table: str, columns: str, index_name: str | None = None) -> str:
        """Create an index on ``table(columns)``. PostgreSQL allows an anonymous
        index; other engines need an explicit name (``index_name``)."""
        return f"CREATE INDEX ON {table} ({columns})"

    def in_list(self, col_sql: str, values) -> tuple[str, list]:
        """Return ``(sql_fragment, params)`` for ``col IN (values)``.

        Default expands to ``IN (%s, %s, ...)``. PostgreSQL overrides this with a
        single ``= ANY(%s)`` array bind (its historical, index-friendly form).
        ``values`` must be non-empty."""
        placeholders = ", ".join(["%s"] * len(values))
        return f"{col_sql} IN ({placeholders})", list(values)

    def not_in_list(self, col_sql: str, values) -> tuple[str, list]:
        """``(sql_fragment, params)`` for ``col NOT IN (values)``. PostgreSQL uses
        ``!= ALL(%s)`` (array bind); others expand to ``NOT IN (...)``."""
        placeholders = ", ".join(["%s"] * len(values))
        return f"{col_sql} NOT IN ({placeholders})", list(values)

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

    # ── date / time + analytical fragments ──────────────────────────────────
    # All take/return SQL fragment strings. PostgreSQL returns its native idioms
    # so migrated builders stay equivalent to today on PG. ``n``/``unit`` are
    # caller-validated (ints / fixed keywords), never user input.
    def date_add(self, date_expr: str, n, unit: str = "day") -> str:
        """``date_expr`` plus ``n`` units (``unit`` in {day, month, year})."""
        raise NotImplementedError

    def date_sub(self, date_expr: str, n, unit: str = "day") -> str:
        """``date_expr`` minus ``n`` units."""
        raise NotImplementedError

    def interval_literal(self, n, unit: str = "day") -> str:
        """A standalone interval value (e.g. for a window-frame bound). Not all
        engines have one — SQL Server raises."""
        raise NotImplementedError

    def date_diff_days(self, end_expr: str, start_expr: str) -> str:
        """Whole days between two dates (``end - start``)."""
        raise NotImplementedError

    def date_trunc(self, unit: str, expr: str) -> str:
        """Truncate a date/timestamp to ``unit`` (day/month/year)."""
        raise NotImplementedError

    def extract(self, part: str, expr: str) -> str:
        """Extract a calendar field (year/month/day) as a number."""
        raise NotImplementedError

    def length(self, expr: str) -> str:
        return f"LENGTH({expr})"

    def least(self, a: str, b: str) -> str:
        return f"LEAST({a}, {b})"

    def greatest(self, a: str, b: str) -> str:
        return f"GREATEST({a}, {b})"

    def percentile_cont(self, fraction, order_expr: str) -> str:
        # Standard SQL — supported by PostgreSQL, Oracle and SQL Server 2012+.
        return f"PERCENTILE_CONT({fraction}) WITHIN GROUP (ORDER BY {order_expr})"

    def make_date(self, year: str, month: str, day: str) -> str:
        """Build a DATE from year/month/day expressions."""
        raise NotImplementedError

    def age_years(self, end_expr: str, start_expr: str) -> str:
        """Whole years between two dates (calendar age)."""
        raise NotImplementedError

    def months_between(self, end_expr: str, start_expr: str) -> str:
        """Whole months between two dates."""
        raise NotImplementedError

    def int_series_cte(self, name: str, start_expr: str, end_expr: str) -> str:
        """A CTE body (for a ``WITH`` list) yielding column ``y`` over the integer
        range [start, end]. PostgreSQL uses generate_series; other engines use a
        recursive CTE."""
        raise NotImplementedError

    def count_filter(self, condition: str) -> str:
        """``COUNT(*)`` restricted to rows matching ``condition``."""
        return f"SUM(CASE WHEN {condition} THEN 1 ELSE 0 END)"

    def sum_filter(self, value_expr: str, condition: str) -> str:
        return f"SUM(CASE WHEN {condition} THEN {value_expr} ELSE 0 END)"
