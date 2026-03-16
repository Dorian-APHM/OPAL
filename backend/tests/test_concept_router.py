"""Tests for concept/router.py — Concept exploration endpoints.

These endpoints require OMOP CDM connections, so we mock the connection layer.
"""
import pytest
from unittest.mock import patch, MagicMock
from tests.omop_mock import make_omop_conn, DictRow


@pytest.fixture
def client():
    from tests.conftest import TestClient, app
    return TestClient(app)


@pytest.fixture
def cdm_name(client):
    """Create a test CDM."""
    client.post("/api/cdm/", json={
        "name": "concept_test_cdm",
        "db_host": "db.example.com",
        "db_port": 5432,
        "db_name": "testdb",
        "db_user": "user",
        "db_password": "pass",
        "omop_schema": "omop_cdm",
    })
    return "concept_test_cdm"


def _mock_concept_conn():
    """Create a mock connection for concept queries."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cursor


@patch("modules.concept.router.get_omop_connection")
@patch("modules.concept.router.decrypt_password")
def test_search_concepts(mock_decrypt, mock_get_conn, client, cdm_name):
    """Search concepts returns results."""
    mock_decrypt.return_value = "pass"
    conn, cursor = _mock_concept_conn()
    mock_get_conn.return_value = conn

    cursor.fetchall.return_value = [
        DictRow({"concept_id": 201826, "concept_name": "Type 2 diabetes",
                 "concept_code": "E11", "domain_id": "Condition",
                 "vocabulary_id": "SNOMED", "concept_class_id": "Clinical Finding",
                 "standard_concept": "S", "_total_count": 1}),
    ]
    cursor.description = [("concept_id",), ("concept_name",)]

    resp = client.get(f"/api/concepts/search?cdm_name={cdm_name}&q=diabetes")
    assert resp.status_code == 200
    data = resp.json()
    assert "concepts" in data


@patch("modules.concept.router.get_omop_connection")
@patch("modules.concept.router.decrypt_password")
def test_search_concepts_empty(mock_decrypt, mock_get_conn, client, cdm_name):
    """Empty search returns empty results."""
    mock_decrypt.return_value = "pass"
    conn, cursor = _mock_concept_conn()
    mock_get_conn.return_value = conn
    cursor.fetchall.return_value = []

    resp = client.get(f"/api/concepts/search?cdm_name={cdm_name}&q=nonexistent_xyz")
    assert resp.status_code == 200


@patch("modules.concept.router.get_omop_connection")
@patch("modules.concept.router.decrypt_password")
def test_concept_details(mock_decrypt, mock_get_conn, client, cdm_name):
    """Get concept details returns concept info."""
    mock_decrypt.return_value = "pass"
    conn, cursor = _mock_concept_conn()
    mock_get_conn.return_value = conn

    # Main concept query
    cursor.fetchone.return_value = DictRow({
        "concept_id": 201826, "concept_name": "Type 2 diabetes",
        "concept_code": "E11", "domain_id": "Condition",
        "vocabulary_id": "SNOMED", "concept_class_id": "Clinical Finding",
        "standard_concept": "S", "valid_start_date": "2020-01-01",
        "valid_end_date": "2099-12-31", "invalid_reason": None,
    })
    cursor.fetchall.return_value = []

    resp = client.get(f"/api/concepts/details/201826?cdm_name={cdm_name}")
    assert resp.status_code == 200


@patch("modules.concept.router.get_omop_connection")
@patch("modules.concept.router.decrypt_password")
def test_concept_hierarchy(mock_decrypt, mock_get_conn, client, cdm_name):
    """Get concept hierarchy returns ancestors and descendants."""
    mock_decrypt.return_value = "pass"
    conn, cursor = _mock_concept_conn()
    mock_get_conn.return_value = conn

    cursor.fetchall.return_value = []

    resp = client.get(f"/api/concepts/hierarchy/201826?cdm_name={cdm_name}")
    assert resp.status_code == 200


@patch("modules.concept.router.get_omop_connection")
@patch("modules.concept.router.decrypt_password")
def test_list_domains(mock_decrypt, mock_get_conn, client, cdm_name):
    """List concept domains."""
    mock_decrypt.return_value = "pass"
    conn, cursor = _mock_concept_conn()
    mock_get_conn.return_value = conn

    cursor.fetchall.return_value = [
        DictRow({"domain_id": "Condition", "count": 5000}),
        DictRow({"domain_id": "Drug", "count": 3000}),
    ]

    resp = client.get(f"/api/concepts/domains?cdm_name={cdm_name}")
    assert resp.status_code == 200


@patch("modules.concept.router.get_omop_connection")
@patch("modules.concept.router.decrypt_password")
def test_list_vocabularies(mock_decrypt, mock_get_conn, client, cdm_name):
    """List vocabularies."""
    mock_decrypt.return_value = "pass"
    conn, cursor = _mock_concept_conn()
    mock_get_conn.return_value = conn

    cursor.fetchall.return_value = [
        DictRow({"vocabulary_id": "SNOMED", "count": 10000}),
    ]

    resp = client.get(f"/api/concepts/vocabularies?cdm_name={cdm_name}")
    assert resp.status_code == 200


def test_search_no_cdm(client):
    """Search without valid CDM returns 404."""
    resp = client.get("/api/concepts/search?cdm_name=nonexistent&q=test")
    assert resp.status_code == 404


@patch("modules.concept.router.get_omop_connection")
@patch("modules.concept.router.decrypt_password")
def test_source_values(mock_decrypt, mock_get_conn, client, cdm_name):
    """Get source values for a concept."""
    mock_decrypt.return_value = "pass"
    conn, cursor = _mock_concept_conn()
    mock_get_conn.return_value = conn
    cursor.fetchall.return_value = []

    resp = client.get(f"/api/concepts/source-values/201826?cdm_name={cdm_name}")
    assert resp.status_code == 200
