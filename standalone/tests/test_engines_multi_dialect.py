"""The bricks must emit engine-correct SQL, not PostgreSQL-only SQL.

The dialect layer (``db.dialects``) is shared with the server; these tests pin
the standalone side of it: the schema map carries the engine, and the query
layer routes identifiers, pagination, placeholders and date arithmetic through
the dialect.
"""
import pytest

from conftest import FakeRow
from db.dialects import get_dialect
from opal_standalone import glue
from opal_standalone.config import CdmConnection
from opal_standalone.omop import dialect_for, schema_map, table_ref

CRITERIA = {
    "inclusion": {
        "operator": "AND",
        "criteria": [{"id": "a", "domain": "Condition", "concepts": [{"concept_id": 201826}]}],
    }
}


class RecordingCursor:
    """Captures the SQL/params handed to the driver and replays fixed rows."""

    def __init__(self, rows, calls):
        self._rows = [FakeRow(row) for row in rows]
        self.calls = calls
        keys = list(self._rows[0].keys()) if self._rows else ["col"]
        self.description = [(name,) for name in keys]

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RecordingConnection:
    """Minimal connection exposing ``.dialect``, like the real wrappers do."""

    def __init__(self, db_type, rows=None):
        self.dialect = get_dialect(db_type)
        self.calls: list[tuple] = []
        self._rows = rows or []

    def cursor(self, *args, **kwargs):
        return RecordingCursor(self._rows, self.calls)

    def rollback(self):
        return None


def _cdm(db_type: str) -> CdmConnection:
    return CdmConnection(
        name=f"cdm-{db_type}", host="h", database="d", user="u", db_type=db_type,
        schema="omop_cdm", schema_categories={"vocabulary": "omop_vocab"},
    )


@pytest.mark.parametrize("db_type,label", [
    ("postgresql", "PostgreSQL"), ("oracle", "Oracle"), ("sqlserver", "SQL Server"),
])
def test_connection_config_selects_the_dialect(db_type, label):
    cdm = _cdm(db_type)
    assert dialect_for(cdm).label == label
    # The SQL builders only receive the schema map — it must carry the engine.
    assert schema_map(cdm)._dialect.name == db_type


def test_schema_map_still_resolves_categories_per_engine():
    schema = schema_map(_cdm("oracle"))
    assert schema.t("person") == "omop_cdm.person"
    assert schema.t("concept") == "omop_vocab.concept"


def test_kaplan_meier_sql_uses_engine_date_arithmetic():
    pg = glue.kaplan_meier_sql(CRITERIA, CRITERIA, schema_map(_cdm("postgresql")),
                               time_at_risk_end=365)
    oracle = glue.kaplan_meier_sql(CRITERIA, CRITERIA, schema_map(_cdm("oracle")),
                                   time_at_risk_end=365)
    assert "INTERVAL '365 days'" in pg
    assert "INTERVAL '365 days'" not in oracle
    assert "cohort_start + 365" in oracle


def test_concept_search_paginates_per_engine():
    for db_type, expected in (("postgresql", "LIMIT"), ("oracle", "FETCH NEXT"),
                              ("sqlserver", "FETCH NEXT")):
        conn = RecordingConnection(db_type, rows=[{"concept_id": 1, "total_count": 1}])
        glue.search_concepts(conn, schema_map(_cdm(db_type)), q="aspirin", limit=25)
        sql, params = conn.calls[0]
        assert expected in sql.upper()
        assert params, "the search term must be bound, never inlined"


def test_placeholders_are_translated_for_non_postgres_engines():
    conn = RecordingConnection("oracle", rows=[{"concept_id": 1, "total_count": 1}])
    glue.search_concepts(conn, schema_map(_cdm("oracle")), q="aspirin")
    sql, _params = conn.calls[0]
    assert "%s" not in sql, "Oracle uses :1-style placeholders"
    assert ":1" in sql


def test_unmapped_terms_uses_engine_case_insensitive_match():
    for db_type in ("postgresql", "oracle"):
        conn = RecordingConnection(db_type, rows=[{"source_value": "A", "n_records": 1}])
        glue.unmapped_terms(conn, schema_map(_cdm(db_type)), "Condition", limit=10, search="x")
        sql, params = conn.calls[-1]
        upper = sql.upper()
        assert "ILIKE" in upper if db_type == "postgresql" else "LOWER(" in upper
        assert params


def test_table_ref_quotes_through_the_dialect():
    for db_type in ("postgresql", "oracle", "sqlserver"):
        conn = RecordingConnection(db_type)
        reference = table_ref(conn, schema_map(_cdm(db_type)), "concept")
        assert reference.endswith(".concept")
        assert "omop_vocab" in reference


def test_read_only_guard_caps_rows_per_engine():
    for db_type, expected in (("postgresql", "LIMIT"), ("oracle", "FETCH NEXT")):
        conn = RecordingConnection(db_type, rows=[{"n": 1}])
        glue.run_read_only_sql(conn, "SELECT 1 FROM dual", limit=10)
        sql, _ = conn.calls[0]
        assert expected in sql.upper()


class SessionRecordingDialect:
    """Wraps a real dialect to record the session statements issued on connect."""

    def __init__(self, db_type):
        self._inner = get_dialect(db_type)
        self.statements: list[str] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def connect(self, *args, **kwargs):
        recorder = self

        class _Conn:
            def cursor(self, *a, **k):
                class _Cur:
                    def execute(self, sql, params=None):
                        recorder.statements.append(sql)

                    def close(self):
                        return None

                    def __enter__(self):
                        return self

                    def __exit__(self, *exc):
                        return False

                return _Cur()

            def close(self):
                return None

        return _Conn()


@pytest.mark.parametrize("db_type,expected", [
    ("postgresql", "default_transaction_read_only"),
    ("oracle", "SET TRANSACTION READ ONLY"),
])
def test_sessions_are_read_only_by_default(db_type, expected, monkeypatch):
    from opal_standalone import omop

    recorder = SessionRecordingDialect(db_type)
    monkeypatch.setattr(omop, "dialect_for", lambda cdm: recorder)
    omop.connect(_cdm(db_type))
    assert any(expected in statement for statement in recorder.statements)


def test_scratch_table_analyses_opt_out_of_read_only(monkeypatch):
    """Characterization and pathways build session tables — they need writes."""
    from opal_standalone import omop

    recorder = SessionRecordingDialect("postgresql")
    monkeypatch.setattr(omop, "dialect_for", lambda cdm: recorder)
    omop.connect(_cdm("postgresql"), allow_temp_tables=True)
    assert not any("read_only" in s for s in recorder.statements)


def test_cohort_view_opens_scratch_capable_connections():
    """Guard the wiring: those two tabs must ask for a writable session."""
    import inspect

    from opal_standalone.views import cohort

    source = inspect.getsource(cohort)
    for function in ("_tab_characterization", "_tab_pathways"):
        body = source.split(f"def {function}(")[1].split("\ndef ")[0]
        assert "allow_temp_tables=True" in body, f"{function} needs a writable session"
