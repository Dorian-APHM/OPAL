"""Tests for cohort/pathways.py — Sunburst tree builder and pathway helpers."""
import pytest
from modules.cohort.pathways import _build_sunburst_tree, _prune_and_compute_pct


class TestBuildSunburstTree:
    def test_basic_tree(self):
        person_paths = {
            1: ["Drug A", "Drug B"],
            2: ["Drug A", "Drug B"],
            3: ["Drug A", "Drug C"],
            4: ["Drug B"],
            5: ["Drug A", "Drug B"],
        }
        tree = _build_sunburst_tree(person_paths, min_cell_count=1, target_size=5)

        assert tree["name"] == "Target"
        assert tree["count"] == 5
        assert len(tree["children"]) > 0

    def test_min_cell_count_filters(self):
        person_paths = {
            1: ["A", "B"],
            2: ["A", "B"],
            3: ["A", "B"],
            4: ["C"],  # only 1 person
        }
        tree = _build_sunburst_tree(person_paths, min_cell_count=2, target_size=4)

        # "C" should be filtered out (only 1 person < min_cell_count=2)
        child_names = [c["name"] for c in tree["children"]]
        assert "C" not in child_names

    def test_empty_paths(self):
        tree = _build_sunburst_tree({}, min_cell_count=1, target_size=0)
        assert tree["name"] == "Target"
        assert tree["count"] == 0
        assert tree["children"] == []

    def test_single_step_paths(self):
        person_paths = {
            1: ["Drug A"],
            2: ["Drug A"],
            3: ["Drug B"],
        }
        tree = _build_sunburst_tree(person_paths, min_cell_count=1, target_size=3)

        assert len(tree["children"]) == 2
        names = {c["name"] for c in tree["children"]}
        assert names == {"Drug A", "Drug B"}

    def test_deep_paths(self):
        """Multi-level paths produce nested children."""
        person_paths = {
            1: ["A", "B", "C"],
            2: ["A", "B", "C"],
        }
        tree = _build_sunburst_tree(person_paths, min_cell_count=1, target_size=2)
        # A -> B -> C
        assert tree["children"][0]["name"] == "A"
        assert tree["children"][0]["children"][0]["name"] == "B"
        assert tree["children"][0]["children"][0]["children"][0]["name"] == "C"


class TestPruneAndComputePct:
    def test_basic_pruning(self):
        tree = {
            "name": "root",
            "count": 100,
            "pct": 0,
            "children": [
                {"name": "A", "count": 80, "pct": 0, "children": [
                    {"name": "B", "count": 50, "pct": 0, "children": []},
                    {"name": "C", "count": 30, "pct": 0, "children": []},
                ]},
                {"name": "D", "count": 3, "pct": 0, "children": []},  # below min_count=5
            ],
        }
        _prune_and_compute_pct(tree, total=100, min_count=5)

        assert "pct" in tree
        assert tree["pct"] == 100.0
        # "D" should be pruned (count=3 < min_count=5)
        child_names = [c["name"] for c in tree["children"]]
        assert "D" not in child_names
        assert "A" in child_names

    def test_zero_total(self):
        tree = {"name": "root", "count": 0, "pct": 0, "children": []}
        _prune_and_compute_pct(tree, total=0, min_count=1)
        assert tree["pct"] == 0
