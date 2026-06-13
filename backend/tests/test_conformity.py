"""Tests for CDM Conformity validation logic."""
import pytest
from unittest.mock import MagicMock

from modules.quality.conformity import run_conformity_checks, _safe


# ── Helper: sequential mock cursor ──

def _make_mock_conn(table_names, fetchone_sequence):
    """
    Build a mock psycopg2 connection.

    - table_names: list of table name strings returned by information_schema query
    - fetchone_sequence: list of tuples returned by successive fetchone() calls.
      Each element should be a tuple matching the row returned by the query.
    """
    from db.dialects import get_dialect
    conn = MagicMock()
    conn.dialect = get_dialect("postgresql")
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    # Table-existence check (dialect.list_tables) reads positional rows (r[0]).
    cursor.fetchall = MagicMock(return_value=[(t,) for t in table_names])

    # All subsequent calls are fetchone() — return tuples in order
    cursor.fetchone = MagicMock(side_effect=fetchone_sequence)

    return conn


# ── 1. _safe identifier validation ──

def test_safe_valid_identifiers():
    assert _safe("omop_cdm") == "omop_cdm"
    assert _safe("public") == "public"
    assert _safe("Schema_123") == "Schema_123"


def test_safe_rejects_sql_injection():
    with pytest.raises(ValueError):
        _safe("omop; DROP TABLE--")
    with pytest.raises(ValueError):
        _safe("schema name with spaces")
    with pytest.raises(ValueError):
        _safe("123_starts_with_digit")


# ── 2. Table existence checks ──

def test_all_tables_present():
    """All 10 required tables present → 10 pass structure checks."""
    all_tables = [
        "person", "observation_period", "visit_occurrence",
        "condition_occurrence", "drug_exposure", "measurement",
        "procedure_occurrence", "observation", "concept", "vocabulary",
    ]
    # P14 merged queries: each fetchone returns a multi-value tuple
    fetchone_seq = [
        (100, 0, 0),    # person merged: total=100, unmapped_gender=0, future_births=0
        (0,),            # orphan persons (LEFT JOIN with obs_period)
        (0, 0),          # obs_period merged: multi_obs=0, future_obs=0
        # condition_occurrence: total, unmapped, future_dates, orphans (has date + visit FK)
        (1000, 0, 0, 0),
        # drug_exposure: total, unmapped, future_dates, orphans
        (1000, 0, 0, 0),
        # measurement: total, unmapped, future_dates, orphans
        (1000, 0, 0, 0),
        # procedure_occurrence: total, unmapped, future_dates (no visit FK)
        (1000, 0, 0),
        # observation: total, unmapped (no date, no visit FK)
        (1000, 0),
        # visit_occurrence: future dates
        (0,),
    ]
    conn = _make_mock_conn(all_tables, fetchone_seq)
    result = run_conformity_checks(conn, "omop_cdm")

    structure_checks = [c for c in result["checks"] if c["category"] == "Structure"]
    assert len(structure_checks) == 10
    assert all(c["status"] == "pass" for c in structure_checks)


def test_missing_tables():
    """Missing required tables should produce 'fail' structure checks."""
    # Only person and concept exist (no observation_period)
    conn = _make_mock_conn(
        ["person", "concept"],
        [
            (50, 0, 0),  # person merged: total=50, unmapped_gender=0, future_births=0
            # No orphan query (observation_period missing → orphan_persons = total_persons)
        ],
    )
    result = run_conformity_checks(conn, "omop_cdm")

    structure_checks = {c["id"]: c for c in result["checks"] if c["category"] == "Structure"}
    assert structure_checks["table_exists_person"]["status"] == "pass"
    assert structure_checks["table_exists_concept"]["status"] == "pass"
    assert structure_checks["table_exists_visit_occurrence"]["status"] == "fail"
    assert structure_checks["table_exists_observation_period"]["status"] == "fail"
    assert structure_checks["table_exists_drug_exposure"]["status"] == "fail"
    assert result["failures"] >= 8


# ── 3. Person checks ──

def test_persons_without_obs_period_pass():
    """<1% orphan persons → pass."""
    conn = _make_mock_conn(
        ["person", "observation_period"],
        [
            (200, 0, 0),  # person merged: total=200, unmapped_gender=0, future_births=0
            (0,),          # orphan persons
            (0, 0),        # obs_period merged: multi_obs=0, future_obs=0
        ],
    )
    result = run_conformity_checks(conn, "omop_cdm")
    check = next(c for c in result["checks"] if c["id"] == "persons_without_obs_period")
    assert check["status"] == "pass"


def test_persons_without_obs_period_warning():
    """5% orphan persons → warning (1-10% range)."""
    conn = _make_mock_conn(
        ["person", "observation_period"],
        [
            (100, 0, 0),  # person merged
            (5,),          # orphan persons = 5
            (0, 0),        # obs_period merged
        ],
    )
    result = run_conformity_checks(conn, "omop_cdm")
    check = next(c for c in result["checks"] if c["id"] == "persons_without_obs_period")
    assert check["status"] == "warning"
    assert check["value"]["pct"] == 5.0


def test_persons_without_obs_period_fail():
    """15% orphan persons → fail (>=10%)."""
    conn = _make_mock_conn(
        ["person", "observation_period"],
        [
            (100, 0, 0),  # person merged
            (15,),         # orphan persons = 15
            (0, 0),        # obs_period merged
        ],
    )
    result = run_conformity_checks(conn, "omop_cdm")
    check = next(c for c in result["checks"] if c["id"] == "persons_without_obs_period")
    assert check["status"] == "fail"
    assert check["value"]["pct"] == 15.0


def test_future_birth_years():
    """Persons with future birth year → fail."""
    conn = _make_mock_conn(
        ["person"],
        [
            (100, 0, 3),  # person merged: total=100, unmapped_gender=0, future_births=3
            # No obs_period → orphan = total (no separate query)
        ],
    )
    result = run_conformity_checks(conn, "omop_cdm")
    check = next(c for c in result["checks"] if c["id"] == "future_birth_years")
    assert check["status"] == "fail"
    assert check["value"] == 3


def test_future_birth_years_pass():
    """No future birth years → pass."""
    conn = _make_mock_conn(
        ["person"],
        [(100, 0, 0)],  # person merged: all clean
    )
    result = run_conformity_checks(conn, "omop_cdm")
    check = next(c for c in result["checks"] if c["id"] == "future_birth_years")
    assert check["status"] == "pass"


def test_unmapped_gender_warning():
    """3% unmapped gender → warning (1-5% range)."""
    conn = _make_mock_conn(
        ["person"],
        [(100, 3, 0)],  # person merged: total=100, unmapped_gender=3, future_births=0
    )
    result = run_conformity_checks(conn, "omop_cdm")
    check = next(c for c in result["checks"] if c["id"] == "unmapped_gender")
    assert check["status"] == "warning"
    assert check["value"]["pct"] == 3.0


def test_unmapped_gender_fail():
    """10% unmapped gender → fail (>=5%)."""
    conn = _make_mock_conn(
        ["person"],
        [(100, 10, 0)],  # person merged: total=100, unmapped_gender=10
    )
    result = run_conformity_checks(conn, "omop_cdm")
    check = next(c for c in result["checks"] if c["id"] == "unmapped_gender")
    assert check["status"] == "fail"


# ── 4. Observation period checks ──

def test_multiple_obs_periods_warning():
    """Persons with multiple observation periods → warning."""
    conn = _make_mock_conn(
        ["observation_period"],
        [(5, 0)],  # obs_period merged: multi_obs=5, future_obs=0
    )
    result = run_conformity_checks(conn, "omop_cdm")
    check = next(c for c in result["checks"] if c["id"] == "multiple_obs_periods")
    assert check["status"] == "warning"
    assert check["value"] == 5


def test_future_obs_end_dates():
    """Observation periods ending in the future → warning."""
    conn = _make_mock_conn(
        ["observation_period"],
        [(0, 10)],  # obs_period merged: multi_obs=0, future_obs=10
    )
    result = run_conformity_checks(conn, "omop_cdm")
    check = next(c for c in result["checks"] if c["id"] == "future_obs_end_dates")
    assert check["status"] == "warning"
    assert check["value"] == 10


# ── 5. Clinical tables: concept_id=0 checks ──

def test_unmapped_concepts_pass():
    """<5% unmapped concepts → pass."""
    # condition_occurrence has date_col but no visit table → (total, unmapped, future_dates)
    conn = _make_mock_conn(
        ["condition_occurrence"],
        [(1000, 10, 0)],  # total=1000, unmapped=10 (1%), future_dates=0
    )
    result = run_conformity_checks(conn, "omop_cdm")
    check = next(c for c in result["checks"] if c["id"] == "unmapped_concepts_condition_occurrence")
    assert check["status"] == "pass"
    assert check["value"]["pct"] == 1.0


def test_unmapped_concepts_warning():
    """10% unmapped concepts → warning (5-20% range)."""
    # drug_exposure has date_col but no visit table → (total, unmapped, future_dates)
    conn = _make_mock_conn(
        ["drug_exposure"],
        [(1000, 100, 0)],  # total=1000, unmapped=100 (10%), future_dates=0
    )
    result = run_conformity_checks(conn, "omop_cdm")
    check = next(c for c in result["checks"] if c["id"] == "unmapped_concepts_drug_exposure")
    assert check["status"] == "warning"


def test_unmapped_concepts_fail():
    """25% unmapped concepts → fail (>=20%)."""
    # measurement has date_col but no visit table → (total, unmapped, future_dates)
    conn = _make_mock_conn(
        ["measurement"],
        [(1000, 250, 0)],  # total=1000, unmapped=250 (25%), future_dates=0
    )
    result = run_conformity_checks(conn, "omop_cdm")
    check = next(c for c in result["checks"] if c["id"] == "unmapped_concepts_measurement")
    assert check["status"] == "fail"
    assert check["value"]["pct"] == 25.0


def test_empty_clinical_table_warning():
    """Empty clinical table → warning."""
    # procedure_occurrence has date_col but no visit table → (total, unmapped, future_dates)
    conn = _make_mock_conn(
        ["procedure_occurrence"],
        [(0, 0, 0)],  # total=0 → empty table
    )
    result = run_conformity_checks(conn, "omop_cdm")
    check = next(c for c in result["checks"] if c["id"] == "unmapped_concepts_procedure_occurrence")
    assert check["status"] == "warning"
    assert "empty" in check["detail"].lower()


# ── 6. Future date checks ──

def test_future_dates_pass():
    """No future dates → pass."""
    conn = _make_mock_conn(
        ["visit_occurrence"],
        [(0,)],  # future visit dates = 0
    )
    result = run_conformity_checks(conn, "omop_cdm")
    check = next(c for c in result["checks"] if c["id"] == "future_dates_visit_occurrence")
    assert check["status"] == "pass"


def test_future_dates_fail():
    """Many future dates → fail (>=100)."""
    conn = _make_mock_conn(
        ["visit_occurrence"],
        [(200,)],  # future visit dates = 200
    )
    result = run_conformity_checks(conn, "omop_cdm")
    check = next(c for c in result["checks"] if c["id"] == "future_dates_visit_occurrence")
    assert check["status"] == "fail"
    assert check["value"] == 200


# ── 7. Visit orphan checks ──

def test_visit_orphans_pass():
    """No orphan visits → pass."""
    conn = _make_mock_conn(
        ["visit_occurrence", "condition_occurrence", "drug_exposure", "measurement"],
        [
            # condition_occurrence: total, unmapped, future_dates, orphans (has date + visit FK)
            (100, 0, 0, 0),
            # drug_exposure: total, unmapped, future_dates, orphans
            (100, 0, 0, 0),
            # measurement: total, unmapped, future_dates, orphans
            (100, 0, 0, 0),
            # visit_occurrence: future dates
            (0,),
        ],
    )
    result = run_conformity_checks(conn, "omop_cdm")
    orphan_checks = [c for c in result["checks"] if c["id"].startswith("visit_orphans_")]
    assert len(orphan_checks) == 3
    assert all(c["status"] == "pass" for c in orphan_checks)


def test_visit_orphans_fail():
    """Many orphan visits → fail (>=100)."""
    conn = _make_mock_conn(
        ["visit_occurrence", "condition_occurrence"],
        [
            # condition_occurrence: total, unmapped, future_dates, orphans
            (100, 0, 0, 500),
            # visit_occurrence: future dates
            (0,),
        ],
    )
    result = run_conformity_checks(conn, "omop_cdm")
    check = next(c for c in result["checks"] if c["id"] == "visit_orphans_condition_occurrence")
    assert check["status"] == "fail"
    assert check["value"] == 500


# ── 8. Score calculation ──

def test_score_all_pass():
    """Perfect score when all checks pass."""
    all_tables = [
        "person", "observation_period", "visit_occurrence",
        "condition_occurrence", "drug_exposure", "measurement",
        "procedure_occurrence", "observation", "concept", "vocabulary",
    ]
    fetchone_seq = [
        (100, 0, 0),    # person merged
        (0,),            # orphan persons
        (0, 0),          # obs_period merged
        (1000, 0, 0, 0), # condition_occurrence (date + visit FK)
        (1000, 0, 0, 0), # drug_exposure (date + visit FK)
        (1000, 0, 0, 0), # measurement (date + visit FK)
        (1000, 0, 0),    # procedure_occurrence (date, no visit FK)
        (1000, 0),       # observation (no date, no visit FK)
        (0,),            # visit_occurrence future dates
    ]
    conn = _make_mock_conn(all_tables, fetchone_seq)
    result = run_conformity_checks(conn, "omop_cdm")

    assert result["score"] == 100.0
    assert result["failures"] == 0
    assert result["warnings"] == 0
    assert result["passed"] == result["total_checks"]


def test_score_with_failures():
    """Score should reflect the ratio of passed checks."""
    conn = _make_mock_conn(
        ["person", "concept"],
        [(100, 0, 0)],  # person merged: all clean
    )
    result = run_conformity_checks(conn, "omop_cdm")

    assert result["score"] < 50  # Most checks failed (8 missing tables)
    assert result["failures"] >= 8
    assert result["passed"] + result["warnings"] + result["failures"] == result["total_checks"]


# ── 9. Endpoint integration test ──

def test_conformity_endpoint_requires_cdm(client):
    """Conformity endpoint should return 404 for non-existent CDM."""
    resp = client.post("/api/quality/conformity", json={
        "cdm_name": "nonexistent_cdm",
        "domain": "conformity",
    })
    assert resp.status_code == 404
