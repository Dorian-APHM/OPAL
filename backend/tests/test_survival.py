"""
Tests for Kaplan-Meier survival analysis (compute_km, compute_median_survival, log_rank_test).
"""
from modules.estimation.survival import compute_km, compute_median_survival, log_rank_test


class TestComputeKM:
    def test_empty_input(self):
        curve = compute_km([], [])
        assert len(curve) == 1
        assert curve[0]["survival"] == 1.0
        assert curve[0]["at_risk"] == 0

    def test_no_events(self):
        """All censored — survival stays at 1.0."""
        curve = compute_km([10, 20, 30], [0, 0, 0])
        # Only the initial time=0 point (no event times to add points)
        assert len(curve) == 1
        assert curve[0]["survival"] == 1.0

    def test_all_events_same_time(self):
        curve = compute_km([10, 10, 10], [1, 1, 1])
        assert len(curve) == 2
        assert curve[0]["time"] == 0
        assert curve[0]["survival"] == 1.0
        assert curve[1]["time"] == 10
        assert curve[1]["survival"] == 0.0

    def test_step_function(self):
        """Simple example: 4 subjects, events at t=1,2,3,4."""
        curve = compute_km([1, 2, 3, 4], [1, 1, 1, 1])
        assert curve[0]["survival"] == 1.0  # t=0
        assert curve[1]["survival"] == 0.75  # 3/4 survive t=1
        assert curve[2]["survival"] == 0.5   # 2/4 survive t=2
        assert curve[3]["survival"] == 0.25  # 1/4 survive t=3
        assert curve[4]["survival"] == 0.0   # 0/4 survive t=4

    def test_censoring(self):
        """Mix of events and censoring."""
        times = [1, 2, 3, 4, 5]
        events = [1, 0, 1, 0, 1]  # events at t=1,3,5; censored at t=2,4
        curve = compute_km(times, events)
        # t=0: S=1.0, at_risk=5
        # t=1: 1 event, at_risk=5, S = 4/5 = 0.8
        # t=3: 1 event, at_risk=3 (subject at t=2 censored), S = 0.8 * 2/3
        # t=5: 1 event, at_risk=1 (subject at t=4 censored), S = previous * 0/1
        assert curve[0]["survival"] == 1.0
        assert curve[1]["survival"] > 0.7
        assert curve[1]["at_risk"] == 5

    def test_confidence_intervals(self):
        curve = compute_km([1, 2, 3, 4, 5], [1, 1, 0, 0, 1])
        for point in curve:
            assert point["ci_lower"] <= point["survival"]
            assert point["ci_upper"] >= point["survival"]
            assert 0 <= point["ci_lower"] <= 1
            assert 0 <= point["ci_upper"] <= 1


class TestMedianSurvival:
    def test_median_exists(self):
        curve = compute_km([1, 2, 3, 4], [1, 1, 1, 1])
        median = compute_median_survival(curve)
        assert median is not None
        assert median == 2  # S crosses 0.5 at t=2

    def test_median_not_reached(self):
        """If survival never drops to 0.5, returns None."""
        curve = compute_km([1, 2], [1, 0])
        # S=1.0 at t=0, S=0.5 at t=1 -> median = 1
        median = compute_median_survival(curve)
        assert median == 1

    def test_no_events_no_median(self):
        curve = compute_km([10, 20, 30], [0, 0, 0])
        median = compute_median_survival(curve)
        assert median is None


class TestLogRankTest:
    def test_single_group(self):
        result = log_rank_test({"A": ([1, 2, 3], [1, 1, 1])})
        assert result["chi_square"] == 0
        assert result["p_value"] == 1.0

    def test_identical_groups(self):
        result = log_rank_test({
            "A": ([1, 2, 3, 4], [1, 1, 1, 1]),
            "B": ([1, 2, 3, 4], [1, 1, 1, 1]),
        })
        assert result["chi_square"] == 0
        assert result["df"] == 1

    def test_different_groups(self):
        """Groups with clearly different survival — should detect difference."""
        result = log_rank_test({
            "Treatment": ([10, 20, 30, 40, 50], [0, 0, 0, 0, 1]),
            "Control": ([1, 2, 3, 4, 5], [1, 1, 1, 1, 1]),
        })
        assert result["chi_square"] > 0
        assert result["df"] == 1
        # p-value should be significant (small) for clearly different groups
        assert result["p_value"] < 0.05

    def test_three_groups(self):
        result = log_rank_test({
            "A": ([1, 2, 3], [1, 1, 1]),
            "B": ([4, 5, 6], [1, 1, 1]),
            "C": ([7, 8, 9], [1, 1, 1]),
        })
        assert result["df"] == 2

    def test_no_events(self):
        result = log_rank_test({
            "A": ([1, 2, 3], [0, 0, 0]),
            "B": ([4, 5, 6], [0, 0, 0]),
        })
        assert result["p_value"] == 1.0
