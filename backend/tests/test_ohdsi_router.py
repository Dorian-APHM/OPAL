"""
Tests for the OHDSI backend router (thin client of the runner).

The router is gated by OHDSI_MODE. The test environment leaves it "off", so we
test the disabled path directly and monkeypatch the module flag + runner client
for the enabled path. No Docker, no real runner.
"""
import pytest

import modules.ohdsi.router as ohdsi


class FakeResp:
    def __init__(self, status_code=200, json_data=None, content=b"", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._json

    @property
    def text(self):
        return ""


@pytest.fixture
def client():
    from tests.conftest import TestClient, app
    return TestClient(app)


@pytest.fixture
def cdm_name(client):
    client.post("/api/cdm/", json={
        "name": "ohdsi_test_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "testdb",
        "db_user": "user",
        "db_password": "pass",
        "omop_schema": "omop_cdm",
    })
    return "ohdsi_test_cdm"


# --- disabled (default OHDSI_MODE=off) --------------------------------------
def test_config_reports_disabled(client):
    r = client.get("/api/ohdsi/config")
    assert r.status_code == 200 and r.json() == {"enabled": False}


def test_endpoints_return_503_when_disabled(client):
    assert client.post("/api/ohdsi/run/achilles", json={"cdm_name": "x"}).status_code == 503
    assert client.get("/api/ohdsi/status").status_code == 503
    assert client.get("/api/ohdsi/logs/achilles/history").status_code == 503


# --- enabled ----------------------------------------------------------------
@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(ohdsi, "OHDSI_ENABLED", True)


def test_run_forwards_decrypted_credentials(client, cdm_name, enabled, monkeypatch):
    captured = {}

    def fake_runner(method, path, **kwargs):
        captured["method"], captured["path"] = method, path
        captured["json"] = kwargs.get("json")
        return FakeResp(200, {"job_id": "abc123"})

    monkeypatch.setattr(ohdsi, "_runner", fake_runner)
    r = client.post("/api/ohdsi/run/achilles", json={"cdm_name": cdm_name})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "job_id": "abc123"}
    assert captured["path"] == "/jobs"
    payload = captured["json"]
    assert payload["service"] == "achilles"
    assert payload["cdm_name"] == cdm_name
    assert payload["db_password"] == "pass"        # decrypted before forwarding
    assert payload["db_host"] == "db.example.com"


def test_run_unknown_service_400(client, enabled, monkeypatch):
    monkeypatch.setattr(ohdsi, "_runner", lambda *a, **k: FakeResp(200, {}))
    assert client.post("/api/ohdsi/run/bogus", json={"cdm_name": "x"}).status_code == 400


def test_status_reduces_to_latest_per_service(client, enabled, monkeypatch):
    jobs = [  # runner returns newest first
        {"job_id": "2", "service": "achilles", "cdm_name": "cdmB", "status": "done", "launched_by": "u"},
        {"job_id": "1", "service": "achilles", "cdm_name": "cdmA", "status": "error", "launched_by": "u"},
        {"job_id": "3", "service": "dqd", "cdm_name": "cdmA", "status": "running", "launched_by": "u"},
    ]
    monkeypatch.setattr(ohdsi, "_runner", lambda m, p, **k: FakeResp(200, jobs))
    data = client.get("/api/ohdsi/status").json()
    assert data["achilles"] == {
        "status": "done", "log_count": 0, "cdm_name": "cdmB", "job_id": "2",
    }
    assert data["dqd"]["status"] == "running"
    assert data["cdmonboarding"]["status"] == "idle"   # no job
    # job_id lets the UI dismiss one specific finished run.
    assert data["dqd"]["job_id"] == "3"
    assert data["cdmonboarding"]["job_id"] == ""


def test_files_relays_listing(client, enabled, monkeypatch):
    listing = [{"name": "results.json", "path": "cdmA/achilles/results.json", "is_dir": False, "size": 12}]

    def fake_runner(method, path, **kwargs):
        assert path == "/files/cdmA/achilles"
        return FakeResp(200, listing, headers={"content-type": "application/json"})

    monkeypatch.setattr(ohdsi, "_runner", fake_runner)
    r = client.get("/api/ohdsi/files/cdmA/achilles")
    assert r.status_code == 200 and r.json() == listing


def test_stop_requires_running_job(client, enabled, monkeypatch):
    monkeypatch.setattr(ohdsi, "_runner", lambda m, p, **k: FakeResp(200, []))  # no jobs
    assert client.post("/api/ohdsi/stop/achilles").status_code == 400
