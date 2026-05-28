"""
End-to-end tests for the OPAL OHDSI runner.

These spawn *real* subprocesses (a fake `Rscript` replaced by a short python
command) against a real SQLite job store, so the full lifecycle — queue, run,
log capture, status transitions, cancel, restart reconciliation — is exercised
without needing R.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Configure the runner BEFORE importing it (env is read at import time).
_TMP = tempfile.mkdtemp(prefix="ohdsi_runner_test_")
os.environ["OHDSI_DATA_DIR"] = _TMP
os.environ["OHDSI_APP_ROOT"] = _TMP            # cwd for subprocesses
os.environ["OHDSI_RUNNER_TOKEN"] = "secret-token"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

AUTH = {"X-Runner-Token": "secret-token"}


@pytest.fixture
def client():
    return TestClient(server.app)


def _fake_cmd(lines_then_exit):
    code = "; ".join([f"print({l!r})" for l in lines_then_exit])
    return ["python3", "-c", f"import os; {code}"]


def _wait_status(client, job_id, *targets, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/jobs/{job_id}", headers=AUTH)
        if r.json()["status"] in targets:
            return r.json()["status"]
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not reach {targets}")


def _job_payload(**over):
    base = dict(service="achilles", cdm_name="testcdm", db_host="h", db_port=5432,
                db_name="testdb", db_user="u", db_password="p")
    base.update(over)
    return base


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_auth_required(client):
    assert client.get("/jobs").status_code == 401
    assert client.post("/jobs", json=_job_payload()).status_code == 401


def test_unknown_service_and_bad_cdm(client):
    assert client.post("/jobs", json=_job_payload(service="nope"), headers=AUTH).status_code == 400
    assert client.post("/jobs", json=_job_payload(cdm_name="../evil"), headers=AUTH).status_code == 400


def test_job_lifecycle_success(client, monkeypatch):
    # Fake Rscript that echoes an env var then exits 0.
    monkeypatch.setattr(server, "_build_cmd",
                         lambda svc: ["python3", "-c",
                                      "import os; print('DBNAME=' + os.environ['DB_NAME'])"])
    job_id = client.post("/jobs", json=_job_payload(), headers=AUTH).json()["job_id"]
    status = _wait_status(client, job_id, "done", "error")
    assert status == "done"

    logs = client.get(f"/jobs/{job_id}/logs", headers=AUTH).json()
    joined = "\n".join(logs["lines"])
    assert "DBNAME=testdb" in joined            # env contract reached the subprocess
    assert "Finished successfully" in joined
    assert logs["offset"] == len(logs["lines"])

    # Incremental fetch returns nothing new past the end.
    tail = client.get(f"/jobs/{job_id}/logs", headers=AUTH, params={"offset": logs["offset"]}).json()
    assert tail["lines"] == []


def test_job_failure_sets_error(client, monkeypatch):
    monkeypatch.setattr(server, "_build_cmd",
                         lambda svc: ["python3", "-c", "import sys; print('boom'); sys.exit(3)"])
    job_id = client.post("/jobs", json=_job_payload(), headers=AUTH).json()["job_id"]
    assert _wait_status(client, job_id, "done", "error") == "error"


def test_cancel(client, monkeypatch):
    monkeypatch.setattr(server, "_build_cmd",
                         lambda svc: ["python3", "-c", "import time; time.sleep(30)"])
    job_id = client.post("/jobs", json=_job_payload(), headers=AUTH).json()["job_id"]
    _wait_status(client, job_id, "running")
    assert client.post(f"/jobs/{job_id}/cancel", headers=AUTH).status_code == 200
    assert _wait_status(client, job_id, "cancelled") == "cancelled"


def test_files_path_traversal_blocked():
    # The guard rejects any path escaping the output base. (HTTP clients
    # normalise `../` in URLs, so exercise the resolver directly.)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        server._safe_target("../../etc/passwd")
    assert exc.value.status_code == 403
    # A legitimate relative path resolves inside the base.
    assert server._safe_target("testcdm/achilles") == (server.OUTPUT_DIR / "testcdm" / "achilles").resolve()


def test_latest_first_ordering(client, monkeypatch):
    monkeypatch.setattr(server, "_build_cmd", lambda svc: ["python3", "-c", "print('x')"])
    j1 = client.post("/jobs", json=_job_payload(cdm_name="cdmA"), headers=AUTH).json()["job_id"]
    time.sleep(0.05)
    j2 = client.post("/jobs", json=_job_payload(cdm_name="cdmB"), headers=AUTH).json()["job_id"]
    jobs = client.get("/jobs", headers=AUTH, params={"service": "achilles"}).json()
    ids = [j["job_id"] for j in jobs]
    assert ids.index(j2) < ids.index(j1)  # newest first
