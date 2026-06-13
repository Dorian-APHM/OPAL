"""Tests for the CDM database-engine dialect abstraction.

PostgreSQL behaviour must be byte-for-byte identical to the historical path; the
generic pool and dialect registry are exercised with fakes (no real Oracle / SQL
Server instance is available)."""
import psycopg2.pool
import pytest

from db.dialects import (
    get_dialect, default_port_for, engine_choices, SUPPORTED_DB_TYPES, DEFAULT_DB_TYPE,
)
from db.dialects.base import Dialect, DictRowCursor


def test_registry_supported_types():
    assert set(SUPPORTED_DB_TYPES) == {"postgresql", "oracle", "sqlserver"}
    assert DEFAULT_DB_TYPE == "postgresql"


def test_get_dialect_default_and_unknown():
    assert get_dialect(None).name == "postgresql"
    assert get_dialect("").name == "postgresql"
    assert get_dialect("oracle").name == "oracle"
    with pytest.raises(ValueError):
        get_dialect("mysql")


def test_default_ports():
    assert default_port_for("postgresql") == 5432
    assert default_port_for("oracle") == 1521
    assert default_port_for("sqlserver") == 1433


def test_engine_choices_shape():
    choices = engine_choices()
    assert {c["value"] for c in choices} == set(SUPPORTED_DB_TYPES)
    pg = next(c for c in choices if c["value"] == "postgresql")
    assert pg["label"] == "PostgreSQL" and pg["default_port"] == 5432


def test_postgres_sql_fragments_are_native():
    pg = get_dialect("postgresql")
    assert pg.ilike("c.concept_name", "%(q)s") == "unaccent(c.concept_name) ILIKE unaccent(%(q)s)"
    assert pg.cast("x", "date") == "(x)::date"
    assert pg.current_date() == "CURRENT_DATE"
    assert pg.extract_year("d") == "EXTRACT(YEAR FROM d)"
    assert pg.limit_offset("%s", "%s") == "LIMIT %s OFFSET %s"


def test_oracle_sql_fragments():
    o = get_dialect("oracle")
    assert o.ilike("col", ":q") == "LOWER(col) LIKE LOWER(:q)"
    assert "FETCH NEXT" in o.limit_offset(":lim", ":off")
    assert o.has_unaccent is False


def test_sqlserver_interval_unsupported():
    ms = get_dialect("sqlserver")
    assert ms.current_date() == "CAST(GETDATE() AS date)"
    with pytest.raises(NotImplementedError):
        ms.interval_days("7")


def test_pyformat_placeholder_translation():
    from db.dialects.base import translate_pyformat
    sql = "SELECT 1 FROM t WHERE a = %s AND b = %s AND c LIKE '50%%'"
    assert translate_pyformat(sql, lambda i: f":{i}") == \
        "SELECT 1 FROM t WHERE a = :1 AND b = :2 AND c LIKE '50%'"
    assert translate_pyformat(sql, lambda i: "?") == \
        "SELECT 1 FROM t WHERE a = ? AND b = ? AND c LIKE '50%'"


def test_dialect_execute_translates_and_preserves_order():
    class FakeCur:
        def __init__(self):
            self.sql = None
            self.params = None
        def execute(self, sql, params):
            self.sql, self.params = sql, params

    # PostgreSQL: passthrough (no regression).
    pg_cur = FakeCur()
    get_dialect("postgresql").execute(pg_cur, "WHERE a=%s AND b=%s", (1, 2))
    assert pg_cur.sql == "WHERE a=%s AND b=%s" and pg_cur.params == (1, 2)

    # Oracle: numeric named placeholders, params as list, same order.
    o_cur = FakeCur()
    get_dialect("oracle").execute(o_cur, "WHERE a=%s AND b=%s", (1, 2))
    assert o_cur.sql == "WHERE a=:1 AND b=:2" and o_cur.params == [1, 2]

    # SQL Server: qmark.
    ms_cur = FakeCur()
    get_dialect("sqlserver").execute(ms_cur, "WHERE a=%s AND b=%s", (1, 2))
    assert ms_cur.sql == "WHERE a=? AND b=?" and ms_cur.params == [1, 2]


def test_quote_ident_per_engine():
    assert get_dialect("postgresql").quote_ident("concept") == '"concept"'
    assert get_dialect("oracle").quote_ident("concept") == '"concept"'
    assert get_dialect("sqlserver").quote_ident("concept") == "[concept]"


def test_dict_row_cursor_maps_rows():
    class FakeCur:
        description = [("a",), ("b",)]
        def fetchone(self):
            return (1, 2)
        def fetchall(self):
            return [(1, 2), (3, 4)]
        def close(self):
            pass

    cur = DictRowCursor(FakeCur())
    assert cur.fetchone() == {"a": 1, "b": 2}
    assert cur.fetchall() == [{"a": 1, "b": 2}, {"a": 3, "b": 4}]


def test_generic_pool_exhaustion_raises_poolerror():
    """The generic (non-PG) pool raises psycopg2.pool.PoolError on exhaustion so
    get_omop_connection's borrowing logic is identical across engines."""
    from db.omop_connector import _GenericPool

    class FakeDialect:
        name = "fake"
        def connect(self, **kw):
            return object()

    pool = _GenericPool(FakeDialect(), {}, minconn=0, maxconn=1)
    c1 = pool.getconn()
    with pytest.raises(psycopg2.pool.PoolError):
        pool.getconn()
    pool.putconn(c1)
    # after returning, a connection is available again
    assert pool.getconn() is not None
