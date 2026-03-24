"""Tests for datamanagement/router.py — Data management endpoints.

Endpoints that hit OMOP are mocked; endpoints using only app DB are tested directly.
"""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    from tests.conftest import TestClient, app
    return TestClient(app)


@pytest.fixture
def cdm_name(client):
    """Create a test CDM."""
    client.post("/api/cdm/", json={
        "name": "dm_test_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "testdb",
        "db_user": "user",
        "db_password": "pass",
        "omop_schema": "omop_cdm",
    })
    return "dm_test_cdm"


def test_cohorts_list_empty(client, cdm_name):
    """List cohorts for data management returns empty when none exist."""
    resp = client.get(f"/api/datamanagement/cohorts?cdm_name={cdm_name}")
    assert resp.status_code == 200
    assert resp.json()["cohorts"] == []


@patch("modules.datamanagement.router.get_omop_connection")
@patch("modules.datamanagement.router.decrypt_password")
def test_tables_list(mock_decrypt, mock_get_conn, client, cdm_name):
    """List available tables in OMOP schema."""
    mock_decrypt.return_value = "pass"
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    from tests.omop_mock import DictRow
    cursor.fetchall.return_value = [
        DictRow({"table_name": "person"}),
        DictRow({"table_name": "visit_occurrence"}),
        DictRow({"table_name": "condition_occurrence"}),
    ]
    mock_get_conn.return_value = conn

    resp = client.get(f"/api/datamanagement/tables?cdm_name={cdm_name}")
    assert resp.status_code == 200
    tables = resp.json()["tables"]
    table_names = [t["table_name"] if isinstance(t, dict) else t for t in tables]
    assert "person" in table_names
    assert "visit_occurrence" in table_names


@patch("modules.datamanagement.router.get_omop_connection")
@patch("modules.datamanagement.router.decrypt_password")
def test_table_columns(mock_decrypt, mock_get_conn, client, cdm_name):
    """List columns for a specific table."""
    mock_decrypt.return_value = "pass"
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    from tests.omop_mock import DictRow
    cursor.fetchall.return_value = [
        DictRow({"column_name": "person_id", "data_type": "integer"}),
        DictRow({"column_name": "year_of_birth", "data_type": "integer"}),
        DictRow({"column_name": "gender_concept_id", "data_type": "integer"}),
    ]
    mock_get_conn.return_value = conn

    resp = client.get(f"/api/datamanagement/tables/person/columns?cdm_name={cdm_name}")
    assert resp.status_code == 200
    columns = resp.json()["columns"]
    assert len(columns) == 3
    assert columns[0]["column_name"] == "person_id"


def test_tables_no_cdm(client):
    """Tables endpoint returns 404 for nonexistent CDM."""
    resp = client.get("/api/datamanagement/tables?cdm_name=nonexistent")
    assert resp.status_code == 404


def test_extract_status_nonexistent(client):
    """Status for nonexistent task returns 404."""
    resp = client.get("/api/datamanagement/extract/status/nonexistent_task")
    assert resp.status_code == 404


def test_extract_cancel_nonexistent(client):
    """Cancel nonexistent task returns 404."""
    resp = client.post("/api/datamanagement/extract/cancel/nonexistent_task")
    assert resp.status_code == 404


def test_extract_active_empty(client):
    """Active extractions returns empty when none running."""
    resp = client.get("/api/datamanagement/extract/active")
    assert resp.status_code == 200
