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


# ──── P0-1: Nested Groups ────


def test_nested_subgroup_or_inside_and():
    """AND group with an OR sub-group: T2DM AND Metformin AND (HbA1c OR Glucose)."""
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
                {"domain": "Drug", "concepts": [1503297], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
            ],
            "groups": [
                {
                    "operator": "OR",
                    "criteria": [
                        {"domain": "Measurement", "concepts": [3004410], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
                        {"domain": "Measurement", "concepts": [3000963], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
                    ],
                }
            ],
        }
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "condition_occurrence" in sql
    assert "drug_exposure" in sql
    assert "measurement" in sql
    # The outer AND should produce INTERSECT between criteria and the sub-group
    assert "INTERSECT" in sql
    # The inner OR sub-group should produce UNION
    assert "UNION" in sql


def test_nested_subgroup_and_inside_or():
    """OR group with an AND sub-group."""
    criteria = {
        "inclusion": {
            "operator": "OR",
            "criteria": [
                {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
            ],
            "groups": [
                {
                    "operator": "AND",
                    "criteria": [
                        {"domain": "Drug", "concepts": [1503297], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
                        {"domain": "Measurement", "concepts": [3004410], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
                    ],
                }
            ],
        }
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "condition_occurrence" in sql
    assert "drug_exposure" in sql
    assert "measurement" in sql
    # Outer OR should produce UNION
    assert "UNION" in sql
    # Inner AND should produce INTERSECT
    assert "INTERSECT" in sql


def test_nested_groups_only_no_criteria():
    """Group with only sub-groups, no direct criteria."""
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [],
            "groups": [
                {
                    "operator": "OR",
                    "criteria": [
                        {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
                        {"domain": "Condition", "concepts": [443238], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
                    ],
                },
                {
                    "operator": "OR",
                    "criteria": [
                        {"domain": "Drug", "concepts": [1503297], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
                        {"domain": "Drug", "concepts": [1510202], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
                    ],
                },
            ],
        }
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "UNION" in sql
    assert "INTERSECT" in sql


def test_deeply_nested_groups():
    """3 levels deep: AND → OR → AND."""
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
            ],
            "groups": [
                {
                    "operator": "OR",
                    "criteria": [
                        {"domain": "Drug", "concepts": [1503297], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
                    ],
                    "groups": [
                        {
                            "operator": "AND",
                            "criteria": [
                                {"domain": "Measurement", "concepts": [3004410], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
                                {"domain": "Measurement", "concepts": [3000963], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
                            ],
                        }
                    ],
                }
            ],
        }
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "condition_occurrence" in sql
    assert "drug_exposure" in sql
    assert "measurement" in sql
    assert "person_id" in sql


# ──── P0-2: Temporal Relations ────


def test_temporal_before_relation():
    """Criterion A (Condition) occurs before criterion B (Drug)."""
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "id": "crit-drug-1",
                    "domain": "Drug",
                    "concepts": [1503297],
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "any", "count": 1},
                },
                {
                    "id": "crit-cond-1",
                    "domain": "Condition",
                    "concepts": [201826],
                    "temporal": {
                        "type": "relative_to_criterion",
                        "reference_criterion_id": "crit-drug-1",
                        "relation": "before",
                        "days_after": 30,
                    },
                    "occurrence": {"type": "any", "count": 1},
                },
            ],
        }
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "rel_temporal" in sql
    assert "a.event_date < ref.event_date" in sql
    assert "INTERVAL '30 days'" in sql


def test_temporal_after_relation():
    """Criterion A occurs after criterion B."""
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "id": "ref-cond",
                    "domain": "Condition",
                    "concepts": [201826],
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "any", "count": 1},
                },
                {
                    "id": "crit-drug",
                    "domain": "Drug",
                    "concepts": [1503297],
                    "temporal": {
                        "type": "relative_to_criterion",
                        "reference_criterion_id": "ref-cond",
                        "relation": "after",
                    },
                    "occurrence": {"type": "any", "count": 1},
                },
            ],
        }
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "a.event_date > ref.event_date" in sql


def test_temporal_overlaps_relation():
    """Criterion A overlaps with criterion B."""
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "id": "ref-visit",
                    "domain": "Visit",
                    "concepts": [9201],
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "any", "count": 1},
                },
                {
                    "id": "crit-cond",
                    "domain": "Condition",
                    "concepts": [201826],
                    "temporal": {
                        "type": "relative_to_criterion",
                        "reference_criterion_id": "ref-visit",
                        "relation": "overlaps",
                    },
                    "occurrence": {"type": "any", "count": 1},
                },
            ],
        }
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "event_end_date" in sql
    assert "a.event_date <" in sql


def test_temporal_contains_relation():
    """Criterion A contains criterion B (A fully wraps B in time)."""
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "id": "ref-drug",
                    "domain": "Drug",
                    "concepts": [1503297],
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "any", "count": 1},
                },
                {
                    "id": "crit-cond",
                    "domain": "Condition",
                    "concepts": [201826],
                    "temporal": {
                        "type": "relative_to_criterion",
                        "reference_criterion_id": "ref-drug",
                        "relation": "contains",
                    },
                    "occurrence": {"type": "any", "count": 1},
                },
            ],
        }
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "a.event_date <= ref.event_date" in sql
    assert "event_end_date" in sql


def test_temporal_with_window():
    """Temporal relation with both days_before and days_after window."""
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "id": "ref-cond",
                    "domain": "Condition",
                    "concepts": [201826],
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "any", "count": 1},
                },
                {
                    "id": "crit-drug",
                    "domain": "Drug",
                    "concepts": [1503297],
                    "temporal": {
                        "type": "relative_to_criterion",
                        "reference_criterion_id": "ref-cond",
                        "relation": "after",
                        "days_before": 7,
                        "days_after": 90,
                    },
                    "occurrence": {"type": "any", "count": 1},
                },
            ],
        }
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "a.event_date > ref.event_date" in sql
    assert "INTERVAL '7 days'" in sql
    assert "INTERVAL '90 days'" in sql


def test_temporal_missing_reference_skips_gracefully():
    """If reference criterion ID doesn't match, return base CTE without error."""
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "id": "crit-a",
                    "domain": "Condition",
                    "concepts": [201826],
                    "temporal": {
                        "type": "relative_to_criterion",
                        "reference_criterion_id": "nonexistent-id",
                        "relation": "before",
                    },
                    "occurrence": {"type": "any", "count": 1},
                },
            ],
        }
    }
    # Should not raise, just skip the temporal constraint
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "condition_occurrence" in sql
    assert "person_id" in sql


# ──── Combined: Nested Groups + Temporal ────


def test_combined_nested_and_temporal():
    """Full example: T2DM before Metformin AND (HbA1c OR Glucose), excluding T1DM."""
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "id": "crit-t2dm",
                    "domain": "Condition",
                    "concepts": [201826],
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "at_least", "count": 2},
                },
                {
                    "id": "crit-met",
                    "domain": "Drug",
                    "concepts": [1503297],
                    "temporal": {
                        "type": "relative_to_criterion",
                        "reference_criterion_id": "crit-t2dm",
                        "relation": "after",
                        "days_after": 30,
                    },
                    "occurrence": {"type": "any", "count": 1},
                },
            ],
            "groups": [
                {
                    "operator": "OR",
                    "criteria": [
                        {
                            "domain": "Measurement",
                            "concepts": [3004410],
                            "temporal": {"type": "any_time"},
                            "occurrence": {"type": "any", "count": 1},
                            "value": {"operator": ">=", "value": 7.0},
                        },
                        {
                            "domain": "Measurement",
                            "concepts": [3000963],
                            "temporal": {"type": "any_time"},
                            "occurrence": {"type": "any", "count": 1},
                            "value": {"operator": ">=", "value": 126.0},
                        },
                    ],
                }
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
    # All tables present
    assert "condition_occurrence" in sql
    assert "drug_exposure" in sql
    assert "measurement" in sql
    # Temporal relation
    assert "a.event_date > ref.event_date" in sql
    # Value constraints
    assert "value_as_number >= 7.0" in sql
    assert "value_as_number >= 126.0" in sql
    # Exclusion
    assert "EXCEPT" in sql
    # Nested group produces UNION
    assert "UNION" in sql
    # Frequency
    assert "HAVING COUNT(*) >= 2" in sql


# ──── Feature 1: Initial Event / Index Date ────


def test_initial_event_within_days_uses_index_cte():
    """within_days/index should reference the initial event CTE when set."""
    criteria = {
        "initial_event_criterion_id": "idx-cond",
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "id": "idx-cond",
                    "domain": "Condition",
                    "concepts": [201826],
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "any", "count": 1},
                },
                {
                    "id": "drug-crit",
                    "domain": "Drug",
                    "concepts": [1503297],
                    "temporal": {
                        "type": "within_days",
                        "relative_to": "index",
                        "days_before": 30,
                        "days_after": 365,
                    },
                    "occurrence": {"type": "any", "count": 1},
                },
            ],
        },
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "condition_occurrence" in sql
    assert "drug_exposure" in sql
    # Should reference the initial event CTE (inc_1) rather than self-joining
    assert "idx.event_date" in sql
    assert "INTERVAL '30 days'" in sql
    assert "INTERVAL '365 days'" in sql


def test_initial_event_without_id_falls_back_to_self_join():
    """without initial_event_criterion_id, within_days/index self-joins."""
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "domain": "Drug",
                    "concepts": [1503297],
                    "temporal": {
                        "type": "within_days",
                        "relative_to": "index",
                        "days_before": 90,
                    },
                    "occurrence": {"type": "any", "count": 1},
                },
            ],
        },
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "drug_exposure" in sql
    # Self-join: uses index_date (old behavior)
    assert "index_date" in sql
    assert "INTERVAL '90 days'" in sql


# ──── Feature 5: Exit Criteria (build_cohort_dated_sql) ────


def test_exit_criteria_fixed_duration():
    """Fixed duration exit criteria in cohort dated SQL."""
    from modules.cohort.sql_builder import build_cohort_dated_sql
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
            ],
        },
        "exit_criteria": {
            "type": "fixed_duration",
            "duration_days": 180,
        },
    }
    sql = build_cohort_dated_sql(criteria, SCHEMA)
    assert "cohort_start_date" in sql
    assert "cohort_end_date" in sql
    assert "180 days" in sql


def test_exit_criteria_end_of_observation():
    """End of observation exit criteria in cohort dated SQL."""
    from modules.cohort.sql_builder import build_cohort_dated_sql
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {"domain": "Condition", "concepts": [201826], "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}},
            ],
        },
        "exit_criteria": {
            "type": "end_of_observation",
        },
    }
    sql = build_cohort_dated_sql(criteria, SCHEMA)
    assert "observation_period_end_date" in sql
    assert "cohort_end_date" in sql


def test_initial_event_affects_cohort_dated():
    """Initial event should determine the date column for cohort_start_date."""
    from modules.cohort.sql_builder import build_cohort_dated_sql
    criteria = {
        "initial_event_criterion_id": "drug-idx",
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "id": "cond-1",
                    "domain": "Condition",
                    "concepts": [201826],
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "any", "count": 1},
                },
                {
                    "id": "drug-idx",
                    "domain": "Drug",
                    "concepts": [1503297],
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "any", "count": 1},
                },
            ],
        },
    }
    sql = build_cohort_dated_sql(criteria, SCHEMA)
    # The initial event is Drug, so the date column should be drug_exposure_start_date
    assert "drug_exposure_start_date" in sql
    assert "cohort_start_date" in sql


# ── same-visit semantics (regression: OR must NOT impose a visit JOIN) ──

def _sv_crit(cid):
    return {"domain": "Condition", "concepts": [cid],
            "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}}


def test_same_visit_and_uses_visit_join():
    """AND + sameVisit must constrain criteria to the same visit_occurrence_id."""
    import re
    criteria = {"inclusion": {"operator": "AND", "sameVisit": True,
                              "criteria": [_sv_crit(1), _sv_crit(2)]}}
    sql = build_cohort_sql(criteria, SCHEMA)
    assert re.search(r"a\.visit_occurrence_id\s*=\s*\w+\.visit_occurrence_id", sql)


def test_same_visit_or_does_not_impose_visit_join():
    """OR + sameVisit must UNION (either criterion matches); 'same visit' is an
    AND-only constraint. Regression guard against re-introducing a visit JOIN
    for OR groups."""
    import re
    criteria = {"inclusion": {"operator": "OR", "sameVisit": True,
                              "criteria": [_sv_crit(1), _sv_crit(2)]}}
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "UNION" in sql
    assert not re.search(r"a\.visit_occurrence_id\s*=\s*\w+\.visit_occurrence_id", sql)
