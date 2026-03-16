"""Tests for quality/domains/observation_period.py — Observation period analysis."""
import pytest
from tests.omop_mock import make_omop_conn


def test_observation_period_basic():
    """Observation period analysis returns all 6 sub-analyses."""
    from modules.quality.domains.observation_period import run_observation_period_analysis

    responses = [
        # 1) Age at first observation
        [{"age": 30, "n": 50}, {"age": 40, "n": 30}, {"age": 50, "n": 20}],
        # 2) Age by gender
        [{"gender_concept_id": 8507, "gender_name": "MALE", "n": 60,
          "mean_age": 42.5, "p10": 25.0, "p25": 33.0, "median_age": 42.0,
          "p75": 52.0, "p90": 60.0}],
        # 3) Observation length months
        [{"months": 6, "n": 20}, {"months": 12, "n": 30}, {"months": 24, "n": 50}],
        # 4) Duration by gender
        [{"gender_concept_id": 8507, "gender_name": "MALE", "n": 100,
          "mean_months": 18.0, "p10": 3.0, "p25": 8.0, "median_months": 15.0,
          "p75": 25.0, "p90": 36.0}],
        # 5) Cumulative observation
        [{"thr": 6, "pct": 100.0}, {"thr": 12, "pct": 80.0}, {"thr": 24, "pct": 50.0}],
        # 6) Continuous observation by year
        [{"year": 2020, "n_persons": 80}, {"year": 2021, "n_persons": 90},
         {"year": 2022, "n_persons": 95}],
    ]
    conn = make_omop_conn(responses)
    result = run_observation_period_analysis(conn, "omop_cdm")

    assert result["domain"] == "ObservationPeriod"
    al = result["achilles_like"]

    assert al["age_at_first_observation"]["age"] == [30, 40, 50]
    assert al["age_at_first_observation"]["count"] == [50, 30, 20]

    assert len(al["age_by_gender"]["rows"]) == 1
    assert al["age_by_gender"]["rows"][0]["gender_name"] == "MALE"
    assert al["age_by_gender"]["rows"][0]["median_age"] == 42.0

    assert al["observation_length_months"]["months"] == [6, 12, 24]
    assert al["observation_length_months"]["n_persons"] == [20, 30, 50]

    assert len(al["duration_by_gender"]["rows"]) == 1

    assert al["cumulative_observation"]["months_threshold"] == [6, 12, 24]
    assert al["cumulative_observation"]["pct_persons"] == [100.0, 80.0, 50.0]

    assert al["continuous_observation_by_year"]["year"] == [2020, 2021, 2022]


def test_observation_period_empty():
    """Observation period analysis handles empty results."""
    from modules.quality.domains.observation_period import run_observation_period_analysis

    responses = [[], [], [], [], [], []]
    conn = make_omop_conn(responses)
    result = run_observation_period_analysis(conn, "omop_cdm")

    al = result["achilles_like"]
    assert al["age_at_first_observation"]["age"] == []
    assert al["age_by_gender"]["rows"] == []
    assert al["observation_length_months"]["months"] == []
    assert al["duration_by_gender"]["rows"] == []
    assert al["cumulative_observation"]["months_threshold"] == []
    assert al["continuous_observation_by_year"]["year"] == []


def test_observation_period_cap_months():
    """Cap months parameter is forwarded correctly."""
    from modules.quality.domains.observation_period import run_observation_period_analysis

    responses = [[], [], [], [], [], []]
    conn = make_omop_conn(responses)
    result = run_observation_period_analysis(conn, "omop_cdm", cap_months=60)

    assert result["achilles_like"]["observation_length_months"]["cap_months"] == 60


def test_observation_period_default_cap():
    """Default cap_months uses config value."""
    from modules.quality.domains.observation_period import run_observation_period_analysis
    from config import DEFAULT_MAX_OBSERVATION_MONTHS

    responses = [[], [], [], [], [], []]
    conn = make_omop_conn(responses)
    result = run_observation_period_analysis(conn, "omop_cdm")

    assert result["achilles_like"]["observation_length_months"]["cap_months"] == DEFAULT_MAX_OBSERVATION_MONTHS


def test_observation_period_null_quantiles():
    """Null quantile values are handled as None."""
    from modules.quality.domains.observation_period import run_observation_period_analysis

    responses = [
        [],
        [{"gender_concept_id": 8507, "gender_name": "MALE", "n": 1,
          "mean_age": None, "p10": None, "p25": None, "median_age": None,
          "p75": None, "p90": None}],
        [],
        [{"gender_concept_id": 8507, "gender_name": "MALE", "n": 1,
          "mean_months": None, "p10": None, "p25": None, "median_months": None,
          "p75": None, "p90": None}],
        [],
        [],
    ]
    conn = make_omop_conn(responses)
    result = run_observation_period_analysis(conn, "omop_cdm")

    row = result["achilles_like"]["age_by_gender"]["rows"][0]
    assert row["mean_age"] is None
    assert row["median_age"] is None
