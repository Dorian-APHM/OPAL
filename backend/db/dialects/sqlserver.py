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

from .base import Dialect, DictRowCursor, translate_pyformat

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

    def execute(self, cursor, sql: str, params=None):
        translated = translate_pyformat(sql, lambda i: "?")
        cursor.execute(translated, list(params) if params is not None else [])
        return cursor

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

    def stream_cursor(self, conn, sql, itersize):
        cur = conn.cursor()
        cur.arraysize = itersize
        cur.execute(sql)
        return DictRowCursor(cur)

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

    def limit_offset(self, limit_ph: str, offset_ph: str) -> str:
        return f"OFFSET {offset_ph} ROWS FETCH NEXT {limit_ph} ROWS ONLY"
