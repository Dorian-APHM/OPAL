"""Integration tests for the FastAPI application."""
import pytest


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "OPAL" in resp.json()["message"]


def test_list_domains(client):
    resp = client.get("/api/quality/domains")
    assert resp.status_code == 200
    domains = resp.json()["domains"]
    assert "Dashboard" in domains
    assert "Person" in domains
    assert len(domains) >= 5


def test_i18n_fr(client):
    resp = client.get("/api/i18n/fr")
    assert resp.status_code == 200
    data = resp.json()
    assert "app" in data
    assert "OPAL" in data["app"]["title"]


def test_i18n_en(client):
    resp = client.get("/api/i18n/en")
    assert resp.status_code == 200
    data = resp.json()
    assert data["app"]["quality"] == "Quality"


def test_i18n_unknown_lang(client):
    resp = client.get("/api/i18n/xx")
    assert resp.status_code == 404


def test_list_cdms_empty(client):
    resp = client.get("/api/cdm/")
    assert resp.status_code == 200
    assert resp.json()["cdms"] == []


def test_create_cdm(client):
    resp = client.post("/api/cdm/", json={
        "name": "test_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "test_db",
        "db_user": "test_user",
        "db_password": "test_pass",
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "test_cdm"


def test_create_cdm_defaults_to_postgresql(client):
    """A CDM created without db_type defaults to postgresql (backward compatible)."""
    client.post("/api/cdm/", json={
        "name": "pg_default_cdm",
        "db_host": "db.example.com", "db_port": 5432,
        "db_name": "test_db", "db_user": "u", "db_password": "p",
    })
    cdms = {c["name"]: c for c in client.get("/api/cdm/").json()["cdms"]}
    assert cdms["pg_default_cdm"]["db_type"] == "postgresql"


def test_create_cdm_with_oracle_db_type(client):
    """db_type is accepted and round-tripped for non-PostgreSQL engines."""
    resp = client.post("/api/cdm/", json={
        "name": "oracle_cdm", "db_type": "oracle",
        "db_host": "db.example.com", "db_port": 1521,
        "db_name": "ORCLPDB1", "db_user": "u", "db_password": "p",
    })
    assert resp.status_code == 200
    cdms = {c["name"]: c for c in client.get("/api/cdm/").json()["cdms"]}
    assert cdms["oracle_cdm"]["db_type"] == "oracle"


def test_create_cdm_rejects_unknown_db_type(client):
    resp = client.post("/api/cdm/", json={
        "name": "bad_cdm", "db_type": "mysql",
        "db_host": "db.example.com", "db_port": 3306,
        "db_name": "test_db", "db_user": "u", "db_password": "p",
    })
    assert resp.status_code == 422


def test_list_engines(client):
    resp = client.get("/api/cdm/engines")
    assert resp.status_code == 200
    body = resp.json()
    assert body["default"] == "postgresql"
    values = {e["value"] for e in body["engines"]}
    assert {"postgresql", "oracle", "sqlserver"} == values


def test_create_cdm_persists_db_type_in_db(client):
    """The chosen engine must be written to the cdm_configs row, not just echoed."""
    from tests.conftest import TestSession
    from db.models import CdmConfig

    client.post("/api/cdm/", json={
        "name": "persist_cdm", "db_type": "sqlserver",
        "db_host": "db.example.com", "db_port": 1433,
        "db_name": "test_db", "db_user": "u", "db_password": "p",
    })
    db = TestSession()
    try:
        row = db.query(CdmConfig).filter(CdmConfig.name == "persist_cdm").first()
        assert row is not None
        assert row.db_type == "sqlserver"
    finally:
        db.close()


def test_cdm_without_db_type_persists_as_postgresql(client):
    """A CDM registered with no engine is stored as postgresql (the default that
    existing/legacy CDMs are also backfilled to)."""
    from tests.conftest import TestSession
    from db.models import CdmConfig

    client.post("/api/cdm/", json={
        "name": "legacy_like_cdm",
        "db_host": "db.example.com", "db_port": 5432,
        "db_name": "test_db", "db_user": "u", "db_password": "p",
    })
    db = TestSession()
    try:
        row = db.query(CdmConfig).filter(CdmConfig.name == "legacy_like_cdm").first()
        assert row.db_type == "postgresql"
    finally:
        db.close()


def test_create_duplicate_cdm(client):
    # First create
    client.post("/api/cdm/", json={
        "name": "dup_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "test_db",
        "db_user": "test_user",
        "db_password": "test_pass",
    })
    # Duplicate
    resp = client.post("/api/cdm/", json={
        "name": "dup_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "test_db",
        "db_user": "test_user",
        "db_password": "test_pass",
    })
    assert resp.status_code == 409


def test_list_cdms_after_create(client):
    client.post("/api/cdm/", json={
        "name": "test_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "test_db",
        "db_user": "test_user",
        "db_password": "test_pass",
    })
    resp = client.get("/api/cdm/")
    assert resp.status_code == 200
    cdms = resp.json()["cdms"]
    assert len(cdms) == 1
    assert cdms[0]["name"] == "test_cdm"
    assert cdms[0]["db_host"] == "db.example.com"


def test_get_cdm_settings_defaults(client):
    client.post("/api/cdm/", json={
        "name": "test_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "test_db",
        "db_user": "test_user",
        "db_password": "test_pass",
    })
    resp = client.get("/api/cdm/test_cdm/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["top_concepts"] == 50
    assert data["max_records_per_person"] == 100


def test_update_cdm_settings(client):
    client.post("/api/cdm/", json={
        "name": "test_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "test_db",
        "db_user": "test_user",
        "db_password": "test_pass",
    })
    resp = client.put("/api/cdm/test_cdm/settings", json={
        "top_concepts": 100,
        "max_observation_months": 240,
    })
    assert resp.status_code == 200
    # Verify
    resp = client.get("/api/cdm/test_cdm/settings")
    data = resp.json()
    assert data["top_concepts"] == 100
    assert data["max_observation_months"] == 240


def test_analyze_unknown_cdm(client):
    resp = client.post("/api/quality/analyze", json={
        "cdm_name": "nonexistent",
        "domain": "Person",
    })
    assert resp.status_code == 404


def test_analyze_unknown_domain(client):
    client.post("/api/cdm/", json={
        "name": "test_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "test_db",
        "db_user": "test_user",
        "db_password": "test_pass",
    })
    resp = client.post("/api/quality/analyze", json={
        "cdm_name": "test_cdm",
        "domain": "FakeDomain",
    })
    assert resp.status_code == 400


def test_snapshots_empty(client):
    client.post("/api/cdm/", json={
        "name": "test_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "test_db",
        "db_user": "test_user",
        "db_password": "test_pass",
    })
    resp = client.get("/api/quality/snapshots/test_cdm/Person")
    assert resp.status_code == 200
    assert resp.json()["snapshots"] == []


def test_latest_snapshot_404(client):
    client.post("/api/cdm/", json={
        "name": "test_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "test_db",
        "db_user": "test_user",
        "db_password": "test_pass",
    })
    resp = client.get("/api/quality/snapshots/test_cdm/Person/latest")
    assert resp.status_code == 404


def test_export_unknown_snapshot(client):
    resp = client.get("/api/quality/export/9999/top_concepts")
    assert resp.status_code == 404


def test_export_unknown_table_type(client):
    # Create a snapshot first via direct DB insert
    # For now, just test the 404 case
    resp = client.get("/api/quality/export/1/invalid_type")
    # Should be 404 (no snapshot with id 1) or 400 (invalid type)
    assert resp.status_code in (400, 404)


def test_delete_cdm(client):
    client.post("/api/cdm/", json={
        "name": "test_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "test_db",
        "db_user": "test_user",
        "db_password": "test_pass",
    })
    resp = client.delete("/api/cdm/test_cdm")
    assert resp.status_code == 200
    # Verify gone
    resp = client.get("/api/cdm/")
    assert len(resp.json()["cdms"]) == 0


def test_delete_nonexistent_cdm(client):
    resp = client.delete("/api/cdm/nonexistent")
    assert resp.status_code == 404
