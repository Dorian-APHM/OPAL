"""Tests for quality/domains/person.py — Person domain analysis."""
import pytest
from tests.omop_mock import make_omop_conn


def test_person_basic():
    """Person analysis returns all demographic sections."""
    from modules.quality.domains.person import run_person_analysis

    responses = [
        {"n": 1000},  # total persons
        [  # gender distribution
            {"gender_concept_id": 8507, "concept_name": "MALE", "n": 600},
            {"gender_concept_id": 8532, "concept_name": "FEMALE", "n": 400},
        ],
        [  # birth year distribution
            {"year_of_birth": 1980, "n": 50},
            {"year_of_birth": 1990, "n": 100},
            {"year_of_birth": 2000, "n": 80},
        ],
        [  # race distribution
            {"race_concept_id": 8516, "concept_name": "Black", "n": 300},
            {"race_concept_id": 8527, "concept_name": "White", "n": 700},
        ],
        [  # ethnicity distribution
            {"ethnicity_concept_id": 38003564, "concept_name": "Not Hispanic", "n": 900},
            {"ethnicity_concept_id": 38003563, "concept_name": "Hispanic", "n": 100},
        ],
    ]
    conn = make_omop_conn(responses)
    result = run_person_analysis(conn, "omop_cdm")

    assert result["domain"] == "Person"
    ps = result["achilles_like"]["person_summary"]
    assert ps["total_persons"] == 1000
    assert ps["gender_distribution"]["gender_concept_id"] == [8507, 8532]
    assert ps["gender_distribution"]["gender_name"] == ["MALE", "FEMALE"]
    assert ps["gender_distribution"]["count"] == [600, 400]
    assert ps["birth_year_distribution"]["year_of_birth"] == [1980, 1990, 2000]
    assert ps["birth_year_distribution"]["count"] == [50, 100, 80]
    assert len(ps["race_distribution"]["race_concept_id"]) == 2
    assert len(ps["ethnicity_distribution"]["ethnicity_concept_id"]) == 2


def test_person_zero_persons():
    """Person analysis handles empty database."""
    from modules.quality.domains.person import run_person_analysis

    responses = [
        {"n": 0},
        [],  # no gender
        [],  # no birth years
        [],  # no race
        [],  # no ethnicity
    ]
    conn = make_omop_conn(responses)
    result = run_person_analysis(conn, "omop_cdm")

    ps = result["achilles_like"]["person_summary"]
    assert ps["total_persons"] == 0
    assert ps["gender_distribution"]["count"] == []
    assert ps["birth_year_distribution"]["count"] == []


def test_person_race_column_missing():
    """Person analysis handles missing race column gracefully."""
    from modules.quality.domains.person import run_person_analysis

    responses = [
        {"n": 100},
        [{"gender_concept_id": 8507, "concept_name": "MALE", "n": 100}],
        [{"year_of_birth": 1990, "n": 100}],
        Exception("column race_concept_id does not exist"),  # race fails
        [{"ethnicity_concept_id": 38003564, "concept_name": "Not Hispanic", "n": 100}],
    ]
    conn = make_omop_conn(responses)
    result = run_person_analysis(conn, "omop_cdm")

    ps = result["achilles_like"]["person_summary"]
    assert ps["total_persons"] == 100
    assert ps["race_distribution"]["race_concept_id"] == []
    assert len(ps["ethnicity_distribution"]["ethnicity_concept_id"]) == 1


def test_person_ethnicity_column_missing():
    """Person analysis handles missing ethnicity column gracefully."""
    from modules.quality.domains.person import run_person_analysis

    responses = [
        {"n": 50},
        [{"gender_concept_id": 8532, "concept_name": "FEMALE", "n": 50}],
        [{"year_of_birth": 2000, "n": 50}],
        [{"race_concept_id": 8527, "concept_name": "White", "n": 50}],
        Exception("column ethnicity_concept_id does not exist"),
    ]
    conn = make_omop_conn(responses)
    result = run_person_analysis(conn, "omop_cdm")

    ps = result["achilles_like"]["person_summary"]
    assert ps["ethnicity_distribution"]["ethnicity_concept_id"] == []
    assert ps["race_distribution"]["count"] == [50]


def test_person_null_gender_concept_id():
    """Person analysis handles NULL gender_concept_id."""
    from modules.quality.domains.person import run_person_analysis

    responses = [
        {"n": 10},
        [{"gender_concept_id": None, "concept_name": "UNKNOWN", "n": 10}],
        [],
        [],
        [],
    ]
    conn = make_omop_conn(responses)
    result = run_person_analysis(conn, "omop_cdm")

    ps = result["achilles_like"]["person_summary"]
    assert ps["gender_distribution"]["gender_concept_id"] == [None]
    assert ps["gender_distribution"]["gender_name"] == ["UNKNOWN"]
