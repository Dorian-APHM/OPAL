"""PostgreSQL dialect — the reference engine.

Keeps psycopg2 idioms identical to the historical code path. The connection
pooling itself stays in ``db.omop_connector`` using psycopg2's native
ThreadedConnectionPool; this dialect only provides connect/cursor/session and
the SQL fragment helpers (which return PostgreSQL's native syntax).
"""
from __future__ import annotations

import psycopg2
from psycopg2.extras import RealDictCursor

from .base import Dialect


class PostgresDialect(Dialect):
    name = "postgresql"
    label = "PostgreSQL"
    default_port = 5432
    has_unaccent = True

    def connect(self, host, port, dbname, user, password, *, connect_timeout=10,
                statement_timeout_ms=None, sslmode=None, **opts):
        kwargs = dict(
            host=host, port=port, dbname=dbname, user=user, password=password,
            connect_timeout=connect_timeout,
        )
        if statement_timeout_ms is not None:
            kwargs["options"] = f"-c statement_timeout={statement_timeout_ms}"
        if sslmode:
            kwargs["sslmode"] = sslmode
        return psycopg2.connect(**kwargs)

    def dict_cursor(self, conn):
        return conn.cursor(cursor_factory=RealDictCursor)

    def set_statement_timeout(self, conn, ms: int) -> None:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = %s", (ms,))

    # ── metadata / streaming (kept identical to the historical cache builder) ─
    def table_exists(self, conn, schema, table) -> bool:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name = %s LIMIT 1",
                (schema, table),
            )
            return cur.fetchone() is not None

    def column_exists(self, conn, schema, table, column) -> bool:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s AND column_name = %s LIMIT 1",
                (schema, table, column),
            )
            return cur.fetchone() is not None

    def disable_statement_timeout(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 0")

    def list_columns(self, conn, schema, table):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                (schema, table),
            )
            return [{"column_name": r[0], "data_type": r[1]} for r in cur.fetchall()]

    def list_tables(self, conn, schema):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
                (schema,),
            )
            return {r[0] for r in cur.fetchall()}

    def stream_cursor(self, conn, sql, itersize, params=None):
        # Server-side (named) cursor: streams the result in batches instead of
        # materialising a whole table in client memory.
        import uuid
        cur = conn.cursor(name=f"svcache_{uuid.uuid4().hex}", cursor_factory=RealDictCursor)
        cur.itersize = itersize
        if params is not None:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        return cur

    def quote_ident(self, name: str) -> str:
        # Matches psycopg2.sql.Identifier output so ported builders stay
        # byte-equivalent to the historical SQL on PostgreSQL.
        return f'"{name}"'

    def in_list(self, col_sql: str, values):
        # Single array bind — the historical, index-friendly PostgreSQL form.
        return f"{col_sql} = ANY(%s)", [list(values)]

    # ── SQL fragments (native PostgreSQL) ───────────────────────────────────
    def unaccent(self, expr: str) -> str:
        return f"unaccent({expr})"

    def ilike(self, col_sql: str, param_ph: str) -> str:
        return f"unaccent({col_sql}) ILIKE unaccent({param_ph})"

    def cast(self, expr: str, type_name: str) -> str:
        return f"({expr})::{type_name}"

    def current_date(self) -> str:
        return "CURRENT_DATE"

    def interval_days(self, days_expr: str) -> str:
        return f"({days_expr}) * INTERVAL '1 day'"

    def extract_year(self, expr: str) -> str:
        return f"EXTRACT(YEAR FROM {expr})"

    def limit_offset(self, limit_ph: str, offset_ph: str) -> str:
        return f"LIMIT {limit_ph} OFFSET {offset_ph}"

    # ── date / time + analytical (native PostgreSQL) ────────────────────────
    def date_add(self, date_expr: str, n, unit: str = "day") -> str:
        return f"({date_expr} + INTERVAL '{n} {unit}s')"

    def date_sub(self, date_expr: str, n, unit: str = "day") -> str:
        return f"({date_expr} - INTERVAL '{n} {unit}s')"

    def interval_literal(self, n, unit: str = "day") -> str:
        return f"INTERVAL '{n} {unit}s'"

    def date_diff_days(self, end_expr: str, start_expr: str) -> str:
        return f"(({end_expr}) - ({start_expr}))"

    def date_trunc(self, unit: str, expr: str) -> str:
        return f"date_trunc('{unit}', {expr})"

    def extract(self, part: str, expr: str) -> str:
        return f"EXTRACT({part} FROM {expr})"

    def count_filter(self, condition: str) -> str:
        return f"COUNT(*) FILTER (WHERE {condition})"

    def sum_filter(self, value_expr: str, condition: str) -> str:
        return f"SUM({value_expr}) FILTER (WHERE {condition})"
