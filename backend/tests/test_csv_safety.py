"""Tests for utils/csv_safety.py — CSV formula injection protection."""
import pytest
from utils.csv_safety import csv_safe


class TestCsvSafe:
    """Core csv_safe() function tests."""

    def test_normal_string_unchanged(self):
        assert csv_safe("hello") == "hello"

    def test_number_unchanged(self):
        assert csv_safe(42) == "42"

    def test_none_returns_empty(self):
        assert csv_safe(None) == ""

    def test_empty_string(self):
        assert csv_safe("") == ""

    # ── Dangerous first-char prefixes ──

    def test_equals_prefixed(self):
        assert csv_safe("=1+1") == "'=1+1"

    def test_plus_prefixed(self):
        assert csv_safe("+cmd") == "'+cmd"

    def test_minus_prefixed(self):
        assert csv_safe("-cmd") == "'-cmd"

    def test_at_prefixed(self):
        assert csv_safe("@SUM(A1)") == "'@SUM(A1)"

    def test_tab_prefixed(self):
        """Tab is stripped by .strip(), so '\tcmd' → 'cmd' (safe)."""
        assert csv_safe("\tcmd") == "cmd"

    def test_cr_prefixed(self):
        """CR is stripped by .strip(), so '\rcmd' → 'cmd' (safe)."""
        assert csv_safe("\rcmd") == "cmd"

    def test_tab_in_middle(self):
        """Tab in the middle is kept but string is safe (first char is 'a')."""
        assert csv_safe("a\tcmd") == "a\tcmd"

    # ── M1 fix: whitespace-padded payloads ──

    def test_leading_space_then_equals(self):
        """Regression: ' =1+1' must be caught after stripping."""
        assert csv_safe(" =1+1") == "'=1+1"

    def test_leading_spaces_then_at(self):
        assert csv_safe("   @SUM") == "'@SUM"

    def test_leading_tab_then_equals(self):
        assert csv_safe("\t=cmd") == "'=cmd"

    def test_trailing_space_safe(self):
        """Trailing space on a safe string should be stripped but not prefixed."""
        assert csv_safe("hello  ") == "hello"

    # ── Edge cases ──

    def test_single_dangerous_char(self):
        assert csv_safe("=") == "'="

    def test_boolean_true(self):
        assert csv_safe(True) == "True"

    def test_float(self):
        assert csv_safe(3.14) == "3.14"

    def test_negative_number_prefixed(self):
        """Negative numbers start with '-', so they get prefixed."""
        assert csv_safe(-5) == "'-5"
