"""
Tests for incidence rate calculation engine (compute_incidence, _aggregate, _poisson_ci).
"""
from modules.incidence.engine import compute_incidence, _aggregate, _poisson_ci, _classify_age


class TestAggregate:
    def test_basic_aggregation(self):
        rows = [
            {"had_outcome": 1, "time_days": 365},
            {"had_outcome": 0, "time_days": 365},
            {"had_outcome": 1, "time_days": 180},
        ]
        result = _aggregate(rows)
        assert result["target_count"] == 3
        assert result["outcome_count"] == 2
        assert result["person_years"] > 0
        assert result["incidence_rate"] > 0
        assert result["incidence_proportion"] > 0

    def test_no_outcomes(self):
        rows = [
            {"had_outcome": 0, "time_days": 365},
            {"had_outcome": 0, "time_days": 730},
        ]
        result = _aggregate(rows)
        assert result["outcome_count"] == 0
        assert result["incidence_rate"] == 0
        assert result["incidence_proportion"] == 0

    def test_all_outcomes(self):
        rows = [
            {"had_outcome": 1, "time_days": 100},
            {"had_outcome": 1, "time_days": 200},
        ]
        result = _aggregate(rows)
        assert result["outcome_count"] == 2
        assert result["incidence_proportion"] == 1.0


class TestPoissonCI:
    def test_zero_events(self):
        lower, upper = _poisson_ci(0, 100)
        assert lower == 0.0
        assert upper == 0.0

    def test_zero_person_years(self):
        lower, upper = _poisson_ci(5, 0)
        assert lower == 0.0
        assert upper == 0.0

    def test_positive_events(self):
        lower, upper = _poisson_ci(10, 100)
        assert lower > 0
        assert upper > lower
        assert lower < 10 / 100  # CI should contain the point estimate
        assert upper > 10 / 100


class TestComputeIncidence:
    def test_empty_rows(self):
        result = compute_incidence([], strata=[], age_groups=None)
        assert result["target_count"] == 0
        assert result["outcome_count"] == 0
        assert result["strata"] == []

    def test_basic_no_strata(self):
        rows = [
            {"had_outcome": 1, "time_days": 365, "age": 50, "gender_name": "Male", "calendar_year": 2025},
            {"had_outcome": 0, "time_days": 365, "age": 60, "gender_name": "Female", "calendar_year": 2025},
        ]
        result = compute_incidence(rows, strata=[])
        assert result["target_count"] == 2
        assert result["outcome_count"] == 1
        assert result["strata"] == []

    def test_gender_strata(self):
        rows = [
            {"had_outcome": 1, "time_days": 365, "age": 50, "gender_name": "Male", "calendar_year": 2025},
            {"had_outcome": 0, "time_days": 365, "age": 60, "gender_name": "Female", "calendar_year": 2025},
            {"had_outcome": 1, "time_days": 180, "age": 55, "gender_name": "Male", "calendar_year": 2025},
        ]
        result = compute_incidence(rows, strata=["gender_name"])
        assert len(result["strata"]) == 2
        # Find male stratum
        male = next(s for s in result["strata"] if s["strata_values"]["gender_name"] == "Male")
        assert male["target_count"] == 2
        assert male["outcome_count"] == 2

    def test_age_group_strata(self):
        age_groups = [
            {"min": 0, "max": 49, "label": "<50"},
            {"min": 50, "max": 99, "label": "50+"},
        ]
        rows = [
            {"had_outcome": 1, "time_days": 365, "age": 30, "gender_name": "M", "calendar_year": 2025},
            {"had_outcome": 0, "time_days": 365, "age": 70, "gender_name": "F", "calendar_year": 2025},
        ]
        result = compute_incidence(rows, strata=["age_group"], age_groups=age_groups)
        assert len(result["strata"]) == 2


class TestClassifyAge:
    def test_classify_in_range(self):
        groups = [{"min": 0, "max": 17, "label": "Child"}, {"min": 18, "max": 64, "label": "Adult"}]
        assert _classify_age(10, groups) == "Child"
        assert _classify_age(30, groups) == "Adult"

    def test_classify_out_of_range(self):
        groups = [{"min": 0, "max": 17, "label": "Child"}]
        assert _classify_age(99, groups) == "Other"
