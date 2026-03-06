"""
Tests for the cohort JSON → SQL translation engine.
"""
import pytest
from modules.cohort.sql_builder import (
    build_cohort_sql,
    build_count_sql,
    build_attrition_sql,
    build_sample_sql,
    _criterion_label,
)


SCHEMA = "omop_cdm"


def test_empty_criteria_returns_all_persons():
    sql = build_cohort_sql({}, SCHEMA)
    assert "person_id" in sql
    assert "omop_cdm.person" in sql


def test_single_inclusion_criterion():
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "domain": "Condition",
                    "concepts": [201826],
                    "include_descendants": True,
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "any", "count": 1},
                }
            ],
        }
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "condition_occurrence" in sql
    assert "concept_ancestor" in sql
    assert "201826" in sql
    assert "person_id" in sql


def test_single_criterion_without_descendants():
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "domain": "Drug",
                    "concepts": [1503297],
                    "include_descendants": False,
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "any", "count": 1},
                }
            ],
        }
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "drug_exposure" in sql
    assert "1503297" in sql
    assert "concept_ancestor" not in sql


def test_multiple_criteria_and():
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
                {"domain": "Drug", "concepts": [1503297], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
            ],
        }
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "INTERSECT" in sql
    assert "condition_occurrence" in sql
    assert "drug_exposure" in sql


def test_multiple_criteria_or():
    criteria = {
        "inclusion": {
            "operator": "OR",
            "criteria": [
                {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
                {"domain": "Drug", "concepts": [1503297], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
            ],
        }
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "UNION" in sql


def test_exclusion_criteria():
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
            ],
        },
        "exclusion": {
            "operator": "OR",
            "criteria": [
                {"domain": "Condition", "concepts": [4033004], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
            ],
        },
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "EXCEPT" in sql


def test_demographics_age():
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
            ],
        },
        "demographics": {
            "age": {"min": 18, "max": 80},
        },
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "year_of_birth" in sql
    assert ">= 18" in sql
    assert "<= 80" in sql


def test_demographics_gender():
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
            ],
        },
        "demographics": {
            "gender": [8507, 8532],
        },
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "gender_concept_id" in sql
    assert "8507" in sql
    assert "8532" in sql


def test_occurrence_at_least():
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "domain": "Drug",
                    "concepts": [1503297],
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "at_least", "count": 3},
                },
            ],
        },
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "GROUP BY" in sql
    assert "HAVING COUNT(*) >= 3" in sql


def test_occurrence_exactly():
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "domain": "Condition",
                    "concepts": [201826],
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "exactly", "count": 1},
                },
            ],
        },
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "HAVING COUNT(*) = 1" in sql


def test_value_constraint_measurement():
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "domain": "Measurement",
                    "concepts": [3004410],
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "any", "count": 1},
                    "value": {"operator": ">", "value": 7.0},
                },
            ],
        },
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "value_as_number > 7.0" in sql
    assert "measurement" in sql


def test_value_constraint_between():
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "domain": "Measurement",
                    "concepts": [3004410],
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "any", "count": 1},
                    "value": {"operator": "between", "value": 5.0, "value_high": 10.0},
                },
            ],
        },
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "BETWEEN 5.0 AND 10.0" in sql


def test_absolute_window_temporal():
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "domain": "Condition",
                    "concepts": [201826],
                    "temporal": {"type": "absolute_window", "date_from": "2020-01-01", "date_to": "2023-12-31"},
                    "occurrence": {"type": "any", "count": 1},
                },
            ],
        },
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "2020-01-01" in sql
    assert "2023-12-31" in sql


def test_build_count_sql():
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
            ],
        },
    }
    sql = build_count_sql(criteria, SCHEMA)
    assert "COUNT(DISTINCT person_id)" in sql
    assert "patient_count" in sql


def test_build_attrition_sql():
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
                {"domain": "Drug", "concepts": [1503297], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
            ],
        },
    }
    steps = build_attrition_sql(criteria, SCHEMA)
    assert len(steps) >= 3  # All persons + 2 criteria
    assert steps[0]["step"] == 0
    assert steps[0]["label"] == "All persons"
    assert steps[1]["step"] == 1
    assert steps[2]["step"] == 2


def test_build_sample_sql():
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
            ],
        },
    }
    sql = build_sample_sql(criteria, SCHEMA, limit=5)
    assert "RANDOM()" in sql
    assert "LIMIT 5" in sql
    assert "year_of_birth" in sql
    assert "gender" in sql


def test_unknown_domain_raises():
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {"domain": "FakeDomain", "concepts": [1], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
            ],
        },
    }
    with pytest.raises(ValueError, match="Unknown domain"):
        build_cohort_sql(criteria, SCHEMA)


def test_criterion_label():
    assert _criterion_label({"domain": "Condition", "concepts": [1, 2]}) == "Condition (2 concepts)"
    assert _criterion_label({"domain": "Drug", "concepts": []}) == "Drug"
    assert _criterion_label({"domain": "Measurement"}) == "Measurement"


def test_complex_cohort_full():
    """Full spec example: Diabetics on metformin with HbA1c > 7%, excluding Type 1."""
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "domain": "Condition",
                    "concepts": [201826, 443238],
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "any", "count": 1},
                },
                {
                    "domain": "Drug",
                    "concepts": [1503297],
                    "temporal": {"type": "within_days", "days_before": 365, "relative_to": "index"},
                    "occurrence": {"type": "at_least", "count": 2},
                },
                {
                    "domain": "Measurement",
                    "concepts": [3004410],
                    "value": {"operator": ">", "value": 7.0},
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "any", "count": 1},
                },
            ],
        },
        "exclusion": {
            "operator": "OR",
            "criteria": [
                {
                    "domain": "Condition",
                    "concepts": [4033004],
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "any", "count": 1},
                },
            ],
        },
        "demographics": {
            "age": {"min": 18, "max": 80},
            "gender": [8507, 8532],
        },
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    # Should have all key elements
    assert "condition_occurrence" in sql
    assert "drug_exposure" in sql
    assert "measurement" in sql
    assert "value_as_number > 7.0" in sql
    assert "EXCEPT" in sql
    assert "year_of_birth" in sql
    assert "gender_concept_id" in sql
    assert "HAVING COUNT(*) >= 2" in sql
    assert "person_id" in sql
