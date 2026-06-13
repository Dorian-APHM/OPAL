"""SQL Server dialect — best-effort, NOT yet validated against a real instance.

Uses pyodbc with the Microsoft ODBC Driver. Driver and ODBC driver name are
configurable; imported lazily so the package imports without pyodbc installed.

Known portability gaps the analytical-SQL migration must handle:
  * paramstyle is ``?`` (qmark), not psycopg2 ``%s``.
  * no ``ILIKE`` / ``unaccent`` — case/accent-insensitivity is governed by the
    column collation; ``LOWER()`` covers case.
  * no interval literals — date arithmetic uses ``DATEADD(day, n, col)``.
"""
from __future__ import annotations

import logging
import os

from .base import Dialect, DictRowCursor, translate_pyformat, translate_named_to_positional

logger = logging.getLogger(__name__)

ODBC_DRIVER = os.environ.get("MSSQL_ODBC_DRIVER", "ODBC Driver 18 for SQL Server")


def _driver():
    try:
        import pyodbc  # type: ignore
        return pyodbc
    except ImportError as e:  # pragma: no cover - driver optional
        raise RuntimeError(
            "SQL Server CDM support requires the 'pyodbc' package and a Microsoft ODBC driver."
        ) from e


class SqlServerDialect(Dialect):
    name = "sqlserver"
    label = "SQL Server"
    default_port = 1433
    has_unaccent = False

    def connect(self, host, port, dbname, user, password, *, connect_timeout=10,
                statement_timeout_ms=None, **opts):
        pyodbc = _driver()
        conn_str = (
            f"DRIVER={{{ODBC_DRIVER}}};"
            f"SERVER={host},{port};DATABASE={dbname};"
            f"UID={user};PWD={password};"
            f"TrustServerCertificate=yes;"
        )
        conn = pyodbc.connect(conn_str, timeout=connect_timeout)
        if statement_timeout_ms is not None:
            try:
                conn.timeout = max(1, int(statement_timeout_ms) // 1000)  # query timeout, seconds
            except Exception:
                pass
        return conn

    def dict_cursor(self, conn):
        return DictRowCursor(conn.cursor())

    def quote_ident(self, name: str) -> str:
        return f"[{name}]"

    # ── scratch-table DDL (best-effort) ─────────────────────────────────────
    def create_table_as(self, name: str, select_sql: str) -> str:
        # SQL Server has no CTAS; SELECT … INTO creates the table.
        return f"SELECT * INTO {name} FROM ({select_sql}) _src"

    def create_temp_table_as(self, name: str, select_sql: str) -> str:
        return f"SELECT * INTO {name} FROM ({select_sql}) _src"  # best-effort regular table

    def analyze_table(self, name: str):
        return f"UPDATE STATISTICS {name}"

    def create_index(self, table: str, columns: str, index_name: str | None = None) -> str:
        idx = index_name or f"ix_{abs(hash((table, columns))) % 10_000_000}"
        return f"CREATE INDEX {idx} ON {table} ({columns})"

    def _prepare(self, sql: str, params=None):
        if isinstance(params, dict):
            # pyodbc supports only positional '?': reorder dict values to match.
            return translate_named_to_positional(sql, params, lambda i: "?")
        return translate_pyformat(sql, lambda i: "?"), (list(params) if params is not None else [])

    def execute(self, cursor, sql: str, params=None):
        t_sql, t_params = self._prepare(sql, params)
        cursor.execute(t_sql, t_params)
        return cursor

    def stream_cursor(self, conn, sql, itersize, params=None):
        cur = conn.cursor()
        cur.arraysize = itersize
        t_sql, t_params = self._prepare(sql, params)
        cur.execute(t_sql, t_params)
        return DictRowCursor(cur)

    def set_statement_timeout(self, conn, ms: int) -> None:
        try:
            conn.timeout = max(1, int(ms) // 1000)
        except Exception:
            pass

    # ── metadata / streaming (best-effort) ──────────────────────────────────
    # SQL Server supports INFORMATION_SCHEMA; paramstyle is qmark (?).
    def table_exists(self, conn, schema, table) -> bool:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = ? AND table_name = ?",
                (schema, table),
            )
            return cur.fetchone() is not None

    def column_exists(self, conn, schema, table, column) -> bool:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = ? AND table_name = ? AND column_name = ?",
                (schema, table, column),
            )
            return cur.fetchone() is not None

    def disable_statement_timeout(self, conn) -> None:
        try:
            conn.timeout = 0  # 0 == no query timeout
        except Exception:
            pass

    def list_columns(self, conn, schema, table):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
                (schema, table),
            )
            return [{"column_name": r[0], "data_type": r[1]} for r in cur.fetchall()]

    def list_tables(self, conn, schema):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = ? AND table_type = 'BASE TABLE'",
                (schema,),
            )
            return {r[0] for r in cur.fetchall()}

    # ── SQL fragments (best-effort) ─────────────────────────────────────────
    def ilike(self, col_sql: str, param_ph: str) -> str:
        return f"LOWER({col_sql}) LIKE LOWER({param_ph})"

    def cast(self, expr: str, type_name: str) -> str:
        mapping = {"date": "date", "int": "int", "numeric": "decimal(38,6)",
                   "float": "float", "text": "nvarchar(max)"}
        return f"CAST({expr} AS {mapping.get(type_name, type_name)})"

    def current_date(self) -> str:
        return "CAST(GETDATE() AS date)"

    def interval_days(self, days_expr: str) -> str:
        # SQL Server has no interval value type; date math must use DATEADD(day, n, col).
        raise NotImplementedError(
            "SQL Server has no interval literal; use DATEADD(day, n, col) in the query builder."
        )

    def extract_year(self, expr: str) -> str:
        return f"DATEPART(year, {expr})"

    def random_func(self) -> str:
        return "NEWID()"

    def string_agg(self, expr: str, sep: str, order_by: str | None = None, distinct: bool = False) -> str:
        # SQL Server STRING_AGG has no DISTINCT; callers dedupe upstream.
        ob = f" WITHIN GROUP (ORDER BY {order_by})" if order_by else ""
        return f"STRING_AGG({expr}, '{sep}'){ob}"

    def limit_offset(self, limit_ph: str, offset_ph: str) -> str:
        return f"OFFSET {offset_ph} ROWS FETCH NEXT {limit_ph} ROWS ONLY"

    # ── date / time + analytical (best-effort) ──────────────────────────────
    def date_add(self, date_expr: str, n, unit: str = "day") -> str:
        return f"DATEADD({unit}, {n}, {date_expr})"

    def date_sub(self, date_expr: str, n, unit: str = "day") -> str:
        return f"DATEADD({unit}, -({n}), {date_expr})"

    def interval_literal(self, n, unit: str = "day") -> str:
        # SQL Server has no interval value type — date math must use DATEADD.
        raise NotImplementedError(
            "SQL Server has no interval literal; use date_add/date_sub (DATEADD)."
        )

    def date_diff_days(self, end_expr: str, start_expr: str) -> str:
        return f"DATEDIFF(day, {start_expr}, {end_expr})"

    def date_trunc(self, unit: str, expr: str) -> str:
        # DATETRUNC requires SQL Server 2022+. Fallback for day/month/year via
        # DATEADD/DATEDIFF from the epoch keeps older versions working.
        anchor = "0001-01-01"
        return f"DATEADD({unit}, DATEDIFF({unit}, '{anchor}', {expr}), CAST('{anchor}' AS date))"

    def extract(self, part: str, expr: str) -> str:
        return f"DATEPART({part}, {expr})"

    def length(self, expr: str) -> str:
        return f"LEN({expr})"

    def make_date(self, year: str, month: str, day: str) -> str:
        return f"DATEFROMPARTS({year}, {month}, {day})"

    def age_years(self, end_expr: str, start_expr: str) -> str:
        # Approximate (not birthday-aware); good enough for histogram bucketing.
        return f"DATEDIFF(year, {start_expr}, {end_expr})"

    def months_between(self, end_expr: str, start_expr: str) -> str:
        return f"DATEDIFF(month, {start_expr}, {end_expr})"

    def int_series_cte(self, name: str, start_expr: str, end_expr: str) -> str:
        return (f"{name}(y) AS (SELECT ({start_expr}) AS y"
                f" UNION ALL SELECT y + 1 FROM {name} WHERE y < ({end_expr}))")

    def least(self, a: str, b: str) -> str:
        # LEAST/GREATEST exist only in SQL Server 2022+; CASE is universal.
        return f"(CASE WHEN {a} <= {b} THEN {a} ELSE {b} END)"

    def greatest(self, a: str, b: str) -> str:
        return f"(CASE WHEN {a} >= {b} THEN {a} ELSE {b} END)"
