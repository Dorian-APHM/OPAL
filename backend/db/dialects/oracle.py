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

from .base import Dialect, DictRowCursor, translate_pyformat, translate_named

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
        # DO NOT quote: Oracle folds unquoted identifiers to UPPERCASE, which
        # matches the conventional uppercase OMOP objects (PERSON, OMOP_CDM, …)
        # created by OHDSI DDL. The application config stores names in lowercase;
        # leaving them unquoted lets Oracle's folding resolve them. (safe_identifier
        # already restricts the charset, and OMOP names aren't reserved words.)
        # Quoting (e.g. "person") would force a *lowercase* match and break with
        # ORA-00942 on a standard uppercase CDM.
        return name

    # ── scratch-table DDL (best-effort) ─────────────────────────────────────
    def drop_table_if_exists(self, name: str) -> str:
        # Oracle has no DROP TABLE IF EXISTS; swallow ORA-00942 in a PL/SQL block.
        return (f"BEGIN EXECUTE IMMEDIATE 'DROP TABLE {name}'; "
                f"EXCEPTION WHEN OTHERS THEN IF SQLCODE != -942 THEN RAISE; END IF; END;")

    def analyze_table(self, name: str):
        return None  # rely on Oracle automatic stats; the hint is non-essential

    def create_temp_table_as(self, name: str, select_sql: str) -> str:
        return f"CREATE TABLE {name} AS {select_sql}"  # best-effort regular table

    def create_temp_table(self, name: str, column_defs: str) -> str:
        return f"CREATE TABLE {name} ({column_defs})"

    def create_index(self, table: str, columns: str, index_name: str | None = None) -> str:
        idx = index_name or f"ix_{abs(hash((table, columns))) % 10_000_000}"
        return f"CREATE INDEX {idx} ON {table} ({columns})"

    def _prepare(self, sql: str, params=None):
        if isinstance(params, dict):
            return translate_named(sql, lambda name: f":{name}"), params
        return translate_pyformat(sql, lambda i: f":{i}"), (list(params) if params is not None else [])

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

    def list_columns(self, conn, schema, table):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT LOWER(column_name), LOWER(data_type) FROM all_tab_columns "
                "WHERE owner = UPPER(:1) AND table_name = UPPER(:2) ORDER BY column_id",
                [schema, table],
            )
            return [{"column_name": r[0], "data_type": r[1]} for r in cur.fetchall()]

    def list_tables(self, conn, schema):
        with conn.cursor() as cur:
            cur.execute("SELECT LOWER(table_name) FROM all_tables WHERE owner = UPPER(:1)", [schema])
            return {r[0] for r in cur.fetchall()}

    # ── SQL fragments (best-effort) ─────────────────────────────────────────
    def non_empty(self, col: str) -> str:
        return f"{col} IS NOT NULL"  # Oracle: '' IS NULL, so this suffices

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

    # ── date / time + analytical (best-effort) ──────────────────────────────
    def date_add(self, date_expr: str, n, unit: str = "day") -> str:
        if unit == "day":
            return f"({date_expr} + {n})"            # Oracle DATE + number = days
        if unit == "month":
            return f"ADD_MONTHS({date_expr}, {n})"
        if unit == "year":
            return f"ADD_MONTHS({date_expr}, ({n}) * 12)"
        return f"({date_expr} + NUMTODSINTERVAL({n}, '{unit}'))"

    def date_sub(self, date_expr: str, n, unit: str = "day") -> str:
        if unit == "day":
            return f"({date_expr} - {n})"
        if unit == "month":
            return f"ADD_MONTHS({date_expr}, -({n}))"
        if unit == "year":
            return f"ADD_MONTHS({date_expr}, -({n}) * 12)"
        return f"({date_expr} - NUMTODSINTERVAL({n}, '{unit}'))"

    def interval_literal(self, n, unit: str = "day") -> str:
        return f"NUMTODSINTERVAL({n}, '{unit.upper()}')"

    def date_diff_days(self, end_expr: str, start_expr: str) -> str:
        return f"(({end_expr}) - ({start_expr}))"     # Oracle DATE - DATE = days

    def date_trunc(self, unit: str, expr: str) -> str:
        fmt = {"day": "DD", "month": "MM", "year": "YYYY"}.get(unit, unit)
        return f"TRUNC({expr}, '{fmt}')"

    def extract(self, part: str, expr: str) -> str:
        return f"EXTRACT({part} FROM {expr})"

    def random_func(self) -> str:
        return "DBMS_RANDOM.VALUE"

    def big_int_type(self) -> str:
        return "NUMBER(19)"

    def inline_values_subquery(self, values) -> str:
        # Turn a literal id list into rows via the built-in number collection —
        # no unnest/ARRAY, and keeps the outer IN a single index-friendly subquery.
        ids = ", ".join(str(int(v)) for v in values)
        return f"SELECT column_value AS v FROM TABLE(sys.odcinumberlist({ids}))"

    def release_savepoint_sql(self, name: str) -> str | None:
        return None  # Oracle has no RELEASE SAVEPOINT; savepoints just go out of scope

    def string_agg(self, expr: str, sep: str, order_by: str | None = None, distinct: bool = False) -> str:
        d = "DISTINCT " if distinct else ""
        ob = order_by or expr
        return f"LISTAGG({d}{expr}, '{sep}') WITHIN GROUP (ORDER BY {ob})"

    def make_date(self, year: str, month: str, day: str) -> str:
        return (f"TO_DATE(TO_CHAR({year})||'-'||TO_CHAR({month})||'-'||TO_CHAR({day}),"
                f" 'YYYY-MM-DD')")

    def age_years(self, end_expr: str, start_expr: str) -> str:
        return f"FLOOR(MONTHS_BETWEEN({end_expr}, {start_expr}) / 12)"

    def months_between(self, end_expr: str, start_expr: str) -> str:
        return f"FLOOR(MONTHS_BETWEEN({end_expr}, {start_expr}))"

    def int_series_cte(self, name: str, start_expr: str, end_expr: str) -> str:
        return (f"{name}(y) AS (SELECT ({start_expr}) AS y FROM dual"
                f" UNION ALL SELECT y + 1 FROM {name} WHERE y < ({end_expr}))")
