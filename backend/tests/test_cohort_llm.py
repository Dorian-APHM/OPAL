"""
Tests for the cohort-LLM backend router (thin relay to opal-llm).

Gated by COHORT_LLM_MODE (default "off" in tests). We test the disabled path,
then monkeypatch the module flags + httpx client for the enabled paths. The
on-premise path exercises Settings encryption + per-request LLM injection.
No real opal-llm, no Docker.
"""
import pytest

import modules.cohort_llm_router as clm


class FakeResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        return self._json

    def raise_for_status(self):
        return None  # 200 in all happy-path tests

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
        "name": "clm_test_cdm", "db_host": "db.example.com", "db_port": 5432,
        "db_name": "testdb", "db_user": "user", "db_password": "pass",
        "omop_schema": "omop_cdm",
    })
    return "clm_test_cdm"


@pytest.fixture
def fake_relay(monkeypatch):
    """Capture the payload the router would POST to opal-llm; return a canned draft."""
    captured = {}

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json=None):
            captured["url"], captured["json"] = url, json
            return FakeResp(200, {"demographics": {}, "criteria": []})

    monkeypatch.setattr(clm.httpx, "Client", FakeClient)
    return captured


# --- disabled (default COHORT_LLM_MODE=off) ---------------------------------
def test_config_reports_disabled(client):
    r = client.get("/api/cohort-llm/config")
    assert r.status_code == 200
    assert r.json() == {"enabled": False, "mode": "off"}


def test_draft_503_when_disabled(client):
    assert client.post("/api/cohort-llm/draft",
                       json={"prompt": "x", "cdm_name": "y"}).status_code == 503
    assert client.get("/api/cohort-llm/health").status_code == 503


# --- embedded ---------------------------------------------------------------
def test_draft_embedded_omits_llm(client, cdm_name, fake_relay, monkeypatch):
    monkeypatch.setattr(clm, "COHORT_LLM_ENABLED", True)
    monkeypatch.setattr(clm, "COHORT_LLM_MODE", "embedded")
    r = client.post("/api/cohort-llm/draft", json={"prompt": "diabète", "cdm_name": cdm_name})
    assert r.status_code == 200
    assert fake_relay["json"] == {"prompt": "diabète", "cdm_name": cdm_name}  # no llm field
    assert "llm" not in fake_relay["json"]


# --- on-premise: settings encryption + injection ----------------------------
def test_settings_masks_key(client):
    put = client.put("/api/cohort-llm/settings", json={
        "base_url": "https://llm.chu.fr/v1", "model": "llama3", "api_key": "s3cret"})
    assert put.status_code == 200 and put.json()["has_api_key"] is True

    got = client.get("/api/cohort-llm/settings").json()
    assert got["base_url"] == "https://llm.chu.fr/v1" and got["model"] == "llama3"
    assert got["has_api_key"] is True
    assert "api_key" not in got  # never returned in clear
    # (that the stored key is encrypted AND round-trips is proven by
    #  test_draft_onprem_injects_decrypted_llm below)


def test_settings_rejects_bad_url(client):
    r = client.put("/api/cohort-llm/settings", json={"base_url": "ftp://nope", "model": "m"})
    assert r.status_code == 400


def test_draft_onprem_injects_decrypted_llm(client, cdm_name, fake_relay, monkeypatch):
    client.put("/api/cohort-llm/settings", json={
        "base_url": "https://llm.chu.fr/v1", "model": "llama3", "api_key": "s3cret"})
    monkeypatch.setattr(clm, "COHORT_LLM_ENABLED", True)
    monkeypatch.setattr(clm, "COHORT_LLM_MODE", "on-premise")
    r = client.post("/api/cohort-llm/draft", json={"prompt": "diabète", "cdm_name": cdm_name})
    assert r.status_code == 200
    llm = fake_relay["json"]["llm"]
    assert llm == {"base_url": "https://llm.chu.fr/v1", "model": "llama3", "api_key": "s3cret"}


def test_draft_onprem_503_when_unconfigured(client, cdm_name, fake_relay, monkeypatch):
    # clear any previously-set config via the API (base_url/model -> NULL)
    client.put("/api/cohort-llm/settings", json={"base_url": "", "model": ""})
    monkeypatch.setattr(clm, "COHORT_LLM_ENABLED", True)
    monkeypatch.setattr(clm, "COHORT_LLM_MODE", "on-premise")
    r = client.post("/api/cohort-llm/draft", json={"prompt": "x", "cdm_name": cdm_name})
    assert r.status_code == 503
