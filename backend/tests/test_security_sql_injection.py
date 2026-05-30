"""
Security regression tests for the cohort SQL builder.

These lock in the fix for the CRITICAL arbitrary-SQL-injection vector where a
client-supplied ``nested_cohort_sql`` field was interpolated raw into the
generated SQL (the cohort ``criteria`` comes straight from the request body).

The tests are deliberately written so that *re-introducing* any raw SQL
interpolation of a criterion field makes them fail loudly.
"""
import pytest

from modules.cohort.sql_builder import (
    build_cohort_sql,
    build_count_sql,
    build_attrition_sql,
    build_sample_sql,
)

SCHEMA = "omop_cdm"

# A sentinel SQL payload that must never reach the generated SQL.
INJECTION = "SELECT 1; DROP TABLE person; --pwned"


def _criteria_with_nested(payload: str) -> dict:
    return {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {"domain": "Condition", "nested_cohort_sql": payload},
            ],
        }
    }


@pytest.mark.parametrize(
    "builder",
    [build_cohort_sql, build_count_sql, build_attrition_sql, build_sample_sql],
)
def test_nested_cohort_sql_is_rejected_by_every_builder(builder):
    """No builder may accept a raw ``nested_cohort_sql`` field."""
    with pytest.raises(ValueError):
        builder(_criteria_with_nested(INJECTION), SCHEMA)


def test_injection_payload_never_reaches_generated_sql():
    """Even if the field were silently ignored, the payload must not appear."""
    try:
        sql = build_cohort_sql(_criteria_with_nested(INJECTION), SCHEMA)
    except ValueError:
        return  # rejected — the desired behaviour
    # If a builder ever stops raising, this guards against silent interpolation.
    assert "DROP TABLE" not in sql.upper()
    assert "PWNED" not in sql.upper()


def test_nested_sql_in_subgroup_is_also_rejected():
    """The field must be rejected at any nesting depth, not just the top level."""
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [],
            "groups": [
                {
                    "operator": "OR",
                    "criteria": [
                        {"domain": "Drug", "nested_cohort_sql": INJECTION},
                    ],
                }
            ],
        }
    }
    with pytest.raises(ValueError):
        build_cohort_sql(criteria, SCHEMA)


def test_legitimate_criteria_still_build():
    """Sanity: removing the nested-SQL path must not break normal building."""
    criteria = {
        "inclusion": {
            "operator": "AND",
            "criteria": [
                {
                    "domain": "Condition",
                    "concepts": [201826],
                    "temporal": {"type": "any_time"},
                    "occurrence": {"type": "any", "count": 1},
                }
            ],
        }
    }
    sql = build_cohort_sql(criteria, SCHEMA)
    assert "condition_occurrence" in sql
    assert "201826" in sql
