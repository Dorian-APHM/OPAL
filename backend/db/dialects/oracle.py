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

from .base import Dialect, DictRowCursor

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

    def set_statement_timeout(self, conn, ms: int) -> None:
        try:
            conn.call_timeout = int(ms)
        except Exception:
            pass

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
