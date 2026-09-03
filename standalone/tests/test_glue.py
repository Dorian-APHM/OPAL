import pytest

from opal_standalone import glue
from utils.cdm_helper import SchemaMap

CRITERIA = {
    "inclusion": {
        "operator": "AND",
        "criteria": [
            {"id": "a", "domain": "Condition", "concepts": [{"concept_id": 201826}]},
        ],
    }
}


@pytest.fixture
def schema():
    return SchemaMap("omop_cdm", {"vocabulary": "omop_vocab"})


def test_dated_cohort_sql_uses_the_domain_date_column(schema):
    sql = glue.dated_cohort_sql(CRITERIA, schema)
    assert "MIN(t.condition_start_date) AS cohort_start_date" in sql
    assert "omop_cdm.condition_occurrence t" in sql


def test_dated_cohort_sql_falls_back_to_the_observation_period(schema):
    sql = glue.dated_cohort_sql({"inclusion": {"criteria": []}, "demographics": {"gender": [8532]}},
                                schema)
    assert "observation_period_start_date AS cohort_start_date" in sql


def test_kaplan_meier_sql_honours_strata_and_vocabulary_schema(schema):
    sql = glue.kaplan_meier_sql(CRITERIA, CRITERIA, schema, time_at_risk_end=365,
                                strata=["gender"])
    assert "omop_vocab.concept gc" in sql
    assert "gender_name" in sql
    assert "INTERVAL '365 days'" in sql
    assert "had_event" in sql


@pytest.mark.parametrize("query", ["SELECT 1", "with x as (select 1) select * from x", "EXPLAIN SELECT 1"])
def test_read_only_sql_accepts_select_like_queries(query):
    assert glue.check_read_only_sql(query)


@pytest.mark.parametrize("query", [
    "DELETE FROM person", "UPDATE person SET a = 1", "DROP TABLE person",
    "SELECT 1; DROP TABLE person", "", "   ",
])
def test_read_only_sql_rejects_writes(query):
    with pytest.raises(ValueError):
        glue.check_read_only_sql(query)


def test_validate_criteria_rejects_raw_sql_and_oversized_lists():
    with pytest.raises(ValueError, match="nested_cohort_sql"):
        glue.validate_criteria({"inclusion": {"criteria": [{"nested_cohort_sql": "SELECT 1"}]}})
    with pytest.raises(ValueError, match="exceeds maximum"):
        glue.validate_criteria({
            "inclusion": {"criteria": [{"concepts": [{"concept_id": 1}] * 1001}]}
        })
    with pytest.raises(ValueError, match="integer"):
        glue.validate_criteria({"inclusion": {"criteria": [{"concepts": [{"concept_id": "x"}]}]}})


def test_validate_criteria_accepts_a_normal_definition():
    assert glue.validate_criteria(CRITERIA) is CRITERIA
