"""
Regression test: source_value_cache must stream the (potentially huge) GROUP BY
result via a server-side (named) cursor instead of a client-side cursor that
materialises the whole result in memory before the first fetchmany().
"""
import pytest

from modules.concept import source_value_cache as svc


class _CheckCur:
    """Cursor used for the information_schema existence checks (table/column)."""
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return (1,)  # table / column exists

    def close(self):
        pass


class _MainCur:
    def execute(self, *a, **k):
        pass

    def fetchmany(self, n):
        return []  # no rows → loop exits immediately

    def close(self):
        pass


class _FakeConn:
    def __init__(self):
        self.cursor_kwargs = []

    def cursor(self, *args, **kwargs):
        self.cursor_kwargs.append(kwargs)
        # The streaming cursor is the one created with a server-side name.
        if "name" in kwargs:
            return _MainCur()
        return _CheckCur()


def test_streaming_uses_server_side_named_cursor(setup_db, monkeypatch):
    # Avoid the get_domain_config → _column_exists round-trips.
    monkeypatch.setattr(
        svc, "get_domain_config",
        lambda conn, schema, domain: {
            "table": "drug_exposure",
            "source_value": "drug_source_value",
            "concept_id": "drug_concept_id",
        },
    )

    conn = _FakeConn()
    count = svc.populate_domain("cdm_x", "Drug", conn, "omop_cdm")

    assert count == 0  # no rows from the (mocked) stream
    # At least one cursor must have been opened server-side (with a name=...).
    named = [kw for kw in conn.cursor_kwargs if "name" in kw]
    assert named, f"expected a named (server-side) cursor, got {conn.cursor_kwargs}"
    assert named[0]["name"].startswith("svcache_")
