"""Oracle dialect — best-effort, NOT yet validated against a real instance.

Uses python-oracledb (thin mode, no Oracle client needed). ``db_name`` is treated
as the Oracle *service name*. Driver is imported lazily so the package still
imports when oracledb is not installed.

Known portability gaps the analytical-SQL migration must handle:
  * paramstyle is ``:name`` / ``:1`` (named/numeric), not psycopg2 ``%s``.
  * no ``ILIKE`` / ``unaccent`` — case-insensitivity via ``LOWER()``, accents via
    NLS collation.
  * identifiers are UPPER-cased unless quoted.
"""
from __future__ import annotations

import logging

from .base import Dialect, DictRowCursor, translate_pyformat

logger = logging.getLogger(__name__)


def _driver():
    try:
        import oracledb  # type: ignore
        return oracledb
    except ImportError as e:  # pragma: no cover - driver optional
        raise RuntimeError(
            "Oracle CDM support requires the 'oracledb' package (pip install oracledb)."
        ) from e


class OracleDialect(Dialect):
    name = "oracle"
    label = "Oracle"
    default_port = 1521
    has_unaccent = False

    def connect(self, host, port, dbname, user, password, *, connect_timeout=10,
                statement_timeout_ms=None, **opts):
        oracledb = _driver()
        dsn = oracledb.makedsn(host, port, service_name=dbname)
        conn = oracledb.connect(user=user, password=password, dsn=dsn, tcp_connect_timeout=connect_timeout)
        if statement_timeout_ms is not None:
            try:
                conn.call_timeout = int(statement_timeout_ms)  # round-trip timeout, ms
            except Exception:
                pass
        return conn

    def dict_cursor(self, conn):
        return DictRowCursor(conn.cursor())

    def quote_ident(self, name: str) -> str:
        return f'"{name}"'

    def execute(self, cursor, sql: str, params=None):
        translated = translate_pyformat(sql, lambda i: f":{i}")
        cursor.execute(translated, list(params) if params is not None else [])
        return cursor

    def set_statement_timeout(self, conn, ms: int) -> None:
        try:
            conn.call_timeout = int(ms)
        except Exception:
            pass

    # ── metadata / streaming (best-effort) ──────────────────────────────────
    # Oracle has no information_schema; use the ALL_* data-dictionary views.
    # OMOP-on-Oracle object names are typically stored upper-cased, so match
    # case-insensitively.
    def table_exists(self, conn, schema, table) -> bool:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM all_tables "
                "WHERE owner = UPPER(:1) AND table_name = UPPER(:2) AND ROWNUM = 1",
                [schema, table],
            )
            return cur.fetchone() is not None

    def column_exists(self, conn, schema, table, column) -> bool:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM all_tab_columns "
                "WHERE owner = UPPER(:1) AND table_name = UPPER(:2) AND column_name = UPPER(:3) "
                "AND ROWNUM = 1",
                [schema, table, column],
            )
            return cur.fetchone() is not None

    def disable_statement_timeout(self, conn) -> None:
        try:
            conn.call_timeout = 0  # 0 == no timeout
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
        mapping = {"date": "DATE", "int": "NUMBER(10)", "numeric": "NUMBER",
                   "float": "BINARY_DOUBLE", "text": "VARCHAR2(4000)"}
        return f"CAST({expr} AS {mapping.get(type_name, type_name)})"

    def current_date(self) -> str:
        return "TRUNC(SYSDATE)"

    def interval_days(self, days_expr: str) -> str:
        return f"NUMTODSINTERVAL({days_expr}, 'DAY')"

    def extract_year(self, expr: str) -> str:
        return f"EXTRACT(YEAR FROM {expr})"

    def limit_offset(self, limit_ph: str, offset_ph: str) -> str:
        return f"OFFSET {offset_ph} ROWS FETCH NEXT {limit_ph} ROWS ONLY"
