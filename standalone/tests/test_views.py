"""Unit checks on the view helpers that do not need Streamlit to run."""
import importlib

import pytest

VIEW_MODULES = [
    "quality", "cohort", "concepts", "concept_sets", "mapping",
    "incidence", "estimation", "datamanagement", "lineage",
]


@pytest.mark.parametrize("name", VIEW_MODULES)
def test_every_view_exposes_the_brick_contract(name):
    module = importlib.import_module(f"opal_standalone.views.{name}")
    assert module.TITLE and module.ICON and module.SUBTITLE
    assert callable(module.render)


def test_quality_csv_export_matches_the_api_shapes():
    from opal_standalone.views.quality import snapshot_csv

    snapshot = {
        "cdm_name": "my cdm", "domain": "Drug", "version": 3,
        "results": {
            "achilles_like": {"top_concepts": [
                {"concept_id": "1", "concept_name": "Aspirin", "source_value": "A",
                 "n_records": 10, "n_persons": 5},
            ]},
            "mapping": {"top_unmapped_terms": [
                {"source_value": "=DANGER", "source_name": "x", "count": 3},
            ]},
        },
    }
    filename, concepts_csv = snapshot_csv(snapshot, "top_concepts")
    assert filename == "my_cdm_Drug_v3_top_concepts.csv"
    assert "Aspirin" in concepts_csv

    _, unmapped_csv = snapshot_csv(snapshot, "top_unmapped")
    assert "source_value,source_name,count" in unmapped_csv
    assert "'=DANGER" in unmapped_csv, "CSV formula injection must be neutralised"

    with pytest.raises(ValueError):
        snapshot_csv(snapshot, "not_a_table")


def test_quality_export_availability_detection():
    from opal_standalone.views.quality import _has_export_table

    results = {"achilles_like": {"top_concepts": [{}], "age_by_gender": {"rows": []}}}
    assert _has_export_table(results, "top_concepts")
    assert not _has_export_table(results, "age_by_gender")
    assert not _has_export_table(results, "domain_stats")


def test_cohort_criteria_helpers():
    from opal_standalone.views import cohort

    assert cohort._parse_ids("1, 2;3\n4") == [1, 2, 3, 4]
    assert cohort._parse_codes(" A01 , B02 ") == ["A01", "B02"]
    summary = cohort._criterion_summary({
        "domain": "Drug", "concepts": [{"concept_id": 1}], "source_codes": ["A"],
        "occurrence": {"type": "at_least", "count": 2},
        "temporal": {"type": "absolute_window", "date_from": "2020-01-01", "date_to": "2020-12-31"},
    })
    assert summary.startswith("Drug")
    assert "at_least 2" in summary
    assert "2020-01-01" in summary


def test_mapping_source_to_concept_map_export():
    from opal_standalone.views.mapping import _source_to_concept_map_csv

    csv_text = _source_to_concept_map_csv("cdm", [
        {"source_value": "A01", "source_name": "aspirine", "domain": "Drug",
         "target_concept_id": 1112807, "status": "accepted"},
        {"source_value": "B02", "domain": "Drug", "status": "rejected"},
    ])
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("source_code,")
    assert len(lines) == 2, "rejected decisions must not be exported"
    assert "1112807" in lines[1]


def test_lineage_dot_graph_focus():
    from opal_standalone.views.lineage import _dot

    nodes = {"src": {"layer": "raw"}, "omop": {"layer": "omop"}, "other": {"layer": "raw"}}
    edges = [
        {"source": "src", "target": "omop", "transformation": {"type": "map"}},
        {"source": "other", "target": "src"},
    ]
    full = _dot(nodes, edges, None)
    assert '"src" -> "omop"' in full and '"other" -> "src"' in full

    focused = _dot(nodes, edges, "omop")
    assert '"src" -> "omop"' in focused
    assert '"other" -> "src"' not in focused
