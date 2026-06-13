"""
The source-value cache builder must be engine-agnostic: it routes metadata
checks, timeout disabling and the streaming cursor through the connection's
Dialect. PostgreSQL keeps its server-side named cursor; other engines use their
own metadata views and a batched client cursor.
"""
import pytest

from modules.concept import source_value_cache as svc
from db.dialects import get_dialect


class _RecCur:
    """Records executed SQL and returns rows from a script."""
    def __init__(self, conn):
        self._conn = conn
        self.description = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append(sql)
        return self

    def fetchone(self):
        return (1,)  # existence checks → exists

    def fetchmany(self, n=None):
        return []   # no data rows → loop exits, count 0

    @property
    def arraysize(self):
        return self._conn._arraysize

    @arraysize.setter
    def arraysize(self, v):
        self._conn._arraysize = v

    def close(self):
        pass


class _OracleLikeConn:
    """Fake connection advertising the Oracle dialect."""
    def __init__(self):
        self.executed = []
        self._arraysize = 0
        self.call_timeout = 999

    @property
    def dialect(self):
        return get_dialect("oracle")

    def cursor(self, *args, **kwargs):
        # Oracle dialect never asks for a server-side named cursor.
        assert "name" not in kwargs, "Oracle path must not use a named cursor"
        return _RecCur(self)


def test_oracle_engine_uses_data_dictionary_not_information_schema(setup_db, monkeypatch):
    monkeypatch.setattr(
        svc, "get_domain_config",
        lambda conn, schema, domain: {
            "table": "drug_exposure",
            "source_value": "drug_source_value",
            "concept_id": "drug_concept_id",
        },
    )

    conn = _OracleLikeConn()
    count = svc.populate_domain("cdm_oracle", "Drug", conn, "omop_cdm")

    assert count == 0
    joined = " ".join(conn.executed).lower()
    # Oracle metadata views, not PostgreSQL information_schema.
    assert "all_tables" in joined
    assert "all_tab_columns" in joined
    assert "information_schema" not in joined
    # Timeout disabling went through the dialect (call_timeout reset to 0).
    assert conn.call_timeout == 0
