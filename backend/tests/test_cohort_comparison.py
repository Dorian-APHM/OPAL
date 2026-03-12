"""Unit tests for cohort comparison (SMD computation)."""
import math

from modules.cohort.comparison import (
    compute_smd_continuous,
    compute_smd_binary,
    compare_cohorts,
)


# ── SMD continuous ──

def test_smd_continuous_basic():
    # Known: (50 - 40) / sqrt((10^2 + 10^2) / 2) = 10/10 = 1.0
    assert compute_smd_continuous(50, 10, 40, 10) == 1.0


def test_smd_continuous_identical():
    assert compute_smd_continuous(50, 10, 50, 10) == 0.0


def test_smd_continuous_zero_sd_same_mean():
    assert compute_smd_continuous(50, 0, 50, 0) == 0.0


def test_smd_continuous_zero_sd_diff_mean():
    assert compute_smd_continuous(50, 0, 40, 0) is None


def test_smd_continuous_none_values():
    assert compute_smd_continuous(None, 10, 40, 10) is None
    assert compute_smd_continuous(50, 10, None, 10) is None


def test_smd_continuous_asymmetric_sd():
    # (60 - 50) / sqrt((5^2 + 15^2) / 2) = 10 / sqrt(125) ≈ 0.8944
    result = compute_smd_continuous(60, 5, 50, 15)
    assert result is not None
    assert abs(result - 10 / math.sqrt(125)) < 0.0001


# ── SMD binary ──

def test_smd_binary_basic():
    # (0.6 - 0.4) / sqrt((0.6*0.4 + 0.4*0.6) / 2) = 0.2 / sqrt(0.24) ≈ 0.4082
    result = compute_smd_binary(0.6, 0.4)
    assert result is not None
    assert abs(result - 0.2 / math.sqrt(0.24)) < 0.0001


def test_smd_binary_identical():
    assert compute_smd_binary(0.5, 0.5) == 0.0


def test_smd_binary_both_zero():
    assert compute_smd_binary(0.0, 0.0) == 0.0


def test_smd_binary_both_one():
    assert compute_smd_binary(1.0, 1.0) == 0.0


def test_smd_binary_zero_vs_one():
    # denominator = (0 + 0) / 2 = 0, but p_a != p_b
    assert compute_smd_binary(0.0, 1.0) is None


# ── compare_cohorts ──

def _make_char(size=100, mean_age=50, std_age=10, gender=None, domains=None, measurements=None, visits=None, obs=None):
    """Helper to build a minimal CharacterizationResult dict."""
    return {
        "cohort_size": size,
        "demographics": {
            "age": {"n": size, "mean_age": mean_age, "std_age": std_age,
                    "min_age": 20, "max_age": 80, "q1_age": 40, "median_age": 50, "q3_age": 60},
            "age_groups": [{"age_group": "18-29", "count": 20}, {"age_group": "30-39", "count": 30},
                           {"age_group": "40-49", "count": 50}],
            "gender": gender or [{"label": "MALE", "concept_id": 8507, "count": 60},
                                 {"label": "FEMALE", "concept_id": 8532, "count": 40}],
            "race": [{"label": "White", "concept_id": 1, "count": 80},
                     {"label": "Black", "concept_id": 2, "count": 20}],
            "ethnicity": [{"label": "Not Hispanic", "concept_id": 1, "count": 90},
                          {"label": "Hispanic", "concept_id": 2, "count": 10}],
        },
        "domain_prevalence": domains or [
            {"domain": "Condition", "patients_with_data": 80, "pct_with_data": 80.0,
             "top_concepts": [
                 {"concept_id": 100, "concept_name": "Hypertension", "concept_code": "I10",
                  "vocabulary_id": "ICD10", "n_persons": 50, "n_records": 100, "pct_persons": 50.0},
             ]},
        ],
        "measurement_stats": measurements or [
            {"concept_id": 200, "concept_name": "Glucose", "concept_code": "GLU",
             "n_persons": 70, "pct_persons": 70.0, "mean_value": 100.0, "std_value": 15.0,
             "median_value": 98.0, "min_value": 60, "max_value": 300, "unit": "mg/dL"},
        ],
        "visit_types": visits or [
            {"concept_id": 9201, "concept_name": "Inpatient", "n_persons": 40,
             "n_records": 80, "pct_persons": 40.0},
        ],
        "observation_period": obs or {
            "n_periods": 100, "n_persons": 100, "mean_days": 1000, "std_days": 500,
            "min_days": 30, "max_days": 3000, "median_days": 900,
            "earliest_start": "2010-01-01", "latest_end": "2023-12-31",
        },
    }


def test_compare_identical_cohorts():
    char = _make_char()
    result = compare_cohorts(char, char)
    assert result["cohort_a_size"] == 100
    assert result["cohort_b_size"] == 100
    assert result["demographics"]["age"]["smd"] == 0.0
    # All SMDs should be 0 for identical cohorts
    for v in result["all_variables"]:
        assert v["smd"] is not None
        assert v["smd"] == 0.0, f"Non-zero SMD for {v['variable']}: {v['smd']}"


def test_compare_different_age():
    char_a = _make_char(mean_age=50, std_age=10)
    char_b = _make_char(mean_age=60, std_age=10)
    result = compare_cohorts(char_a, char_b)
    # Age SMD = (50 - 60) / 10 = -1.0
    assert result["demographics"]["age"]["smd"] == -1.0


def test_compare_different_gender():
    char_a = _make_char(gender=[
        {"label": "MALE", "concept_id": 8507, "count": 80},
        {"label": "FEMALE", "concept_id": 8532, "count": 20},
    ])
    char_b = _make_char(gender=[
        {"label": "MALE", "concept_id": 8507, "count": 40},
        {"label": "FEMALE", "concept_id": 8532, "count": 60},
    ])
    result = compare_cohorts(char_a, char_b)
    # Male: 0.8 vs 0.4 → SMD should be non-zero
    male_row = [g for g in result["demographics"]["gender"] if g["label"] == "MALE"][0]
    assert male_row["pct_a"] == 80.0
    assert male_row["pct_b"] == 40.0
    assert male_row["smd"] is not None
    assert abs(male_row["smd"]) > 0.5


def test_compare_missing_concept_in_one():
    """Concept in A but not B should get 0% for B."""
    char_a = _make_char(domains=[
        {"domain": "Condition", "patients_with_data": 80, "pct_with_data": 80.0,
         "top_concepts": [
             {"concept_id": 100, "concept_name": "Hypertension", "concept_code": "I10",
              "vocabulary_id": "ICD10", "n_persons": 50, "n_records": 100, "pct_persons": 50.0},
         ]},
    ])
    char_b = _make_char(domains=[
        {"domain": "Condition", "patients_with_data": 60, "pct_with_data": 60.0,
         "top_concepts": [
             {"concept_id": 200, "concept_name": "Diabetes", "concept_code": "E11",
              "vocabulary_id": "ICD10", "n_persons": 30, "n_records": 60, "pct_persons": 30.0},
         ]},
    ])
    result = compare_cohorts(char_a, char_b)
    cond = [d for d in result["domain_prevalence"] if d["domain"] == "Condition"][0]
    # Both concepts should appear
    cids = {c["concept_id"] for c in cond["concepts"]}
    assert 100 in cids
    assert 200 in cids
    # Hypertension in B = 0%
    hyp = [c for c in cond["concepts"] if c["concept_id"] == 100][0]
    assert hyp["pct_persons_a"] == 50.0
    assert hyp["pct_persons_b"] == 0.0


def test_compare_output_structure():
    result = compare_cohorts(_make_char(), _make_char(mean_age=55))
    # Check all expected keys
    assert "cohort_a_size" in result
    assert "cohort_b_size" in result
    assert "demographics" in result
    assert "domain_prevalence" in result
    assert "measurement_stats" in result
    assert "visit_types" in result
    assert "observation_period" in result
    assert "all_variables" in result
    assert isinstance(result["all_variables"], list)
    assert len(result["all_variables"]) > 0
    # Each variable has category, variable, smd
    for v in result["all_variables"]:
        assert "category" in v
        assert "variable" in v
        assert "smd" in v
