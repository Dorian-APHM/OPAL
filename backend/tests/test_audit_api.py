"""
Tests for audit log endpoints.
"""
import json
import os
from pathlib import Path

import pytest

import audit.logger as _audit_mod
from audit.logger import write_audit_log


@pytest.fixture(autouse=True)
def temp_audit_dir(monkeypatch, tmp_path):
    """Use a temporary directory for audit logs during tests."""
    log_dir = tmp_path / "audit_logs"
    log_dir.mkdir()
    monkeypatch.setattr(_audit_mod, "AUDIT_LOG_DIR", log_dir)
    yield log_dir


def _write_test_entries(dt: str, entries: list[dict]):
    """Helper to write entries to a specific date's log file."""
    log_file = _audit_mod.AUDIT_LOG_DIR / f"{dt}.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        for entry in entries:
            entry.setdefault("ts", f"{dt}T12:00:00+00:00")
            f.write(json.dumps(entry) + "\n")


def _make_entry(**overrides):
    base = {
        "ts": "2099-01-15T14:30:00+00:00",
        "user": "alice",
        "roles": ["chercheur"],
        "action": "quality.analyze",
        "method": "POST",
        "path": "/api/quality/analyze",
        "status": 200,
        "duration_ms": 150,
        "ip": "10.0.0.1",
    }
    base.update(overrides)
    return base


# ──── GET /api/audit/logs ────


def test_audit_logs_empty_date(client):
    resp = client.get("/api/audit/logs", params={"date": "2099-12-31"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["entries"] == []
    assert data["total"] == 0


def test_audit_logs_with_entries(client):
    dt = "2099-01-15"
    _write_test_entries(dt, [
        _make_entry(user="alice", action="quality.analyze"),
        _make_entry(user="bob", action="cohort.create"),
    ])
    resp = client.get("/api/audit/logs", params={"date": dt})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["entries"]) == 2


def test_audit_logs_filter_by_user(client):
    dt = "2099-01-16"
    _write_test_entries(dt, [
        _make_entry(user="alice"),
        _make_entry(user="bob"),
        _make_entry(user="alice"),
    ])
    resp = client.get("/api/audit/logs", params={"date": dt, "user": "alice"})
    data = resp.json()
    assert data["total"] == 2
    assert all(e["user"] == "alice" for e in data["entries"])


def test_audit_logs_filter_by_action(client):
    dt = "2099-01-17"
    _write_test_entries(dt, [
        _make_entry(action="quality.analyze"),
        _make_entry(action="cohort.create"),
        _make_entry(action="quality.compare"),
    ])
    resp = client.get("/api/audit/logs", params={"date": dt, "action": "quality"})
    data = resp.json()
    assert data["total"] == 2
    assert all(e["action"].startswith("quality") for e in data["entries"])


def test_audit_logs_pagination(client):
    dt = "2099-01-18"
    entries = [_make_entry(user=f"user_{i}") for i in range(15)]
    _write_test_entries(dt, entries)

    # Page 1
    resp = client.get("/api/audit/logs", params={"date": dt, "page": 1, "page_size": 5})
    data = resp.json()
    assert data["total"] == 15
    assert len(data["entries"]) == 5
    assert data["page"] == 1
    assert data["total_pages"] == 3

    # Page 3
    resp = client.get("/api/audit/logs", params={"date": dt, "page": 3, "page_size": 5})
    data = resp.json()
    assert len(data["entries"]) == 5


def test_audit_logs_date_range(client):
    for dt in ["2099-02-01", "2099-02-02", "2099-02-03"]:
        _write_test_entries(dt, [_make_entry(user=f"user_{dt}")])

    resp = client.get("/api/audit/logs", params={
        "date_from": "2099-02-01", "date_to": "2099-02-03"
    })
    data = resp.json()
    assert data["total"] == 3


# ──── GET /api/audit/stats ────


def test_audit_stats_empty(client):
    resp = client.get("/api/audit/stats", params={
        "date_from": "2099-12-01", "date_to": "2099-12-31"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_events"] == 0
    assert data["by_user"] == []
    assert data["by_action"] == []


def test_audit_stats_with_data(client):
    dt = "2099-03-01"
    _write_test_entries(dt, [
        _make_entry(user="alice", action="quality.analyze"),
        _make_entry(user="alice", action="cohort.create"),
        _make_entry(user="bob", action="quality.analyze"),
    ])

    resp = client.get("/api/audit/stats", params={"date_from": dt, "date_to": dt})
    data = resp.json()
    assert data["total_events"] == 3

    user_map = {u["user"]: u["count"] for u in data["by_user"]}
    assert user_map["alice"] == 2
    assert user_map["bob"] == 1

    action_map = {a["action"]: a["count"] for a in data["by_action"]}
    assert action_map["quality.analyze"] == 2
    assert action_map["cohort.create"] == 1


# ──── GET /api/audit/dates ────


def test_audit_dates(client):
    for dt in ["2099-04-01", "2099-04-02"]:
        _write_test_entries(dt, [_make_entry()])

    resp = client.get("/api/audit/dates")
    assert resp.status_code == 200
    dates = resp.json()["dates"]
    assert "2099-04-01" in dates
    assert "2099-04-02" in dates


# ──── GET /api/audit/export ────


def test_audit_export_csv(client):
    dt = "2099-05-01"
    _write_test_entries(dt, [
        _make_entry(user="alice", action="quality.analyze"),
        _make_entry(user="bob", action="cohort.create"),
    ])

    resp = client.get("/api/audit/export", params={"date_from": dt, "date_to": dt})
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")

    lines = resp.text.strip().split("\n")
    assert len(lines) == 3  # header + 2 entries
    header = lines[0]
    assert "timestamp" in header
    assert "user" in header
    assert "action" in header


def test_audit_export_csv_filtered(client):
    dt = "2099-05-02"
    _write_test_entries(dt, [
        _make_entry(user="alice"),
        _make_entry(user="bob"),
    ])

    resp = client.get("/api/audit/export", params={
        "date_from": dt, "date_to": dt, "user": "alice"
    })
    lines = resp.text.strip().split("\n")
    assert len(lines) == 2  # header + 1 entry
    assert "alice" in lines[1]


def test_audit_export_empty(client):
    resp = client.get("/api/audit/export", params={
        "date_from": "2099-12-31", "date_to": "2099-12-31"
    })
    assert resp.status_code == 200
    lines = resp.text.strip().split("\n")
    assert len(lines) == 1  # header only


# ──── Unit: write_audit_log ────


def test_write_audit_log_creates_file():
    entry = _make_entry(ts="2099-06-01T10:00:00+00:00")
    write_audit_log(entry)

    log_file = _audit_mod.AUDIT_LOG_DIR / "2099-06-01.jsonl"
    assert log_file.exists()
    content = log_file.read_text().strip()
    parsed = json.loads(content)
    assert parsed["user"] == "alice"
