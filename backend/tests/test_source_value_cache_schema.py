"""
Regression test: the source-value-cache population must pass a SchemaMap (not a
bare schema string) so per-category schemas resolve correctly. A plain string
routed every table (clinical + vocabulary `concept`) to the default schema and
broke population on multi-schema CDMs.
"""
import pytest

from db.models import CdmConfig
from utils.cdm_helper import SchemaMap
from utils.crypto import encrypt_password


def _db():
    from tests.conftest import TestSession
    return TestSession()


class _FakeCursorCtx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        pass


class _FakeConn:
    def cursor(self, *a, **k):
        return _FakeCursorCtx()

    def close(self):
        pass


def test_populate_passes_schema_map(client, monkeypatch):
    # CDM whose vocabulary lives in a different schema than the clinical tables.
    db = _db()
    try:
        db.add(CdmConfig(
            name="multi_schema_cdm",
            db_host="h", db_port=5432, db_name="d", db_user="u",
            db_password_encrypted=encrypt_password("secret"),
            omop_schema="clinical_schema",
            schema_categories={"vocabulary": "vocab_schema"},
        ))
        db.commit()
    finally:
        db.close()

    captured = {}

    def fake_populate_all_domains(cdm_name, conn, schema, cancelled_check=None):
        captured["schema"] = schema

    # Run the worker synchronously and stub the OMOP connection + populate.
    monkeypatch.setattr("utils.thread_pool.submit_task", lambda fn, *a, **k: fn())
    monkeypatch.setattr("modules.concept.router.get_omop_connection", lambda *a, **k: _FakeConn())
    monkeypatch.setattr(
        "modules.concept.source_value_cache.populate_all_domains",
        fake_populate_all_domains,
    )

    resp = client.post("/api/concepts/source-value-cache/populate", params={"cdm_name": "multi_schema_cdm"})
    assert resp.status_code == 200

    schema = captured.get("schema")
    assert isinstance(schema, SchemaMap), f"expected SchemaMap, got {type(schema)}"
    # Vocabulary table resolves to its own schema; clinical tables to the default.
    assert schema.schema_for("concept") == "vocab_schema"
    assert schema.schema_for("drug_exposure") == "clinical_schema"
