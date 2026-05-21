"""Tests for the ETL lineage parser."""
import os
import pytest
from modules.lineage.parser import (
    parse_transformation_block,
    _resolve_java_class,
    _resolve_parent_source,
    split_repertoires,
    build_lineage,
)


# ---------------------------------------------------------------------------
# _resolve_java_class
# ---------------------------------------------------------------------------

def test_resolve_java_class_normal():
    assert _resolve_java_class("cdm_source.tb_diag", "x.java") == "cdm_source.tb_diag"


def test_resolve_java_class_inheritance():
    result = _resolve_java_class("class 'biology_axi' extends 'BiologyBase'", "cdm_source.biology_axi.java")
    assert result == "cdm_source.biology_axi"


def test_resolve_java_class_no_file():
    result = _resolve_java_class("class 'foo' extends 'Bar'", "")
    assert result == "foo"


# ---------------------------------------------------------------------------
# _resolve_parent_source
# ---------------------------------------------------------------------------

def test_resolve_parent_source_from_filename():
    result = _resolve_parent_source("omop_cdm._010_axi_patient_to_person.java", "omop_cdm.person")
    assert result == "omop_cdm.axi_patient"


def test_resolve_parent_source_fallback():
    result = _resolve_parent_source("", "omop_cdm.person")
    assert result == "omop_cdm.person"


# ---------------------------------------------------------------------------
# parse_transformation_block
# ---------------------------------------------------------------------------

SAMPLE_BLOCK = """
<h2 id="test">1/1) Fichier 'omop_cdm._010_axi_patient_to_person.java'</h2>
<h4>Patient identity mapping</h4>
<table>
    <thead>
        <tr>
            <th><em>Source</em><br/>cdm_source.axi_patient</th>
            <th><em>Destination</em><br/>omop_cdm.person</th>
            <th>Commentaires</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>pat_id</td>
            <td>person_id (Long) PK</td>
            <td>primary key</td>
        </tr>
        <tr>
            <td>birth_date</td>
            <td>birth_datetime (Timestamp)</td>
            <td></td>
        </tr>
    </tbody>
</table>
<h4>SQL</h4>
<pre>SELECT * FROM axi_patient</pre>
"""


def test_parse_block_file():
    result = parse_transformation_block(SAMPLE_BLOCK)
    assert result["file"] == "omop_cdm._010_axi_patient_to_person.java"


def test_parse_block_description():
    result = parse_transformation_block(SAMPLE_BLOCK)
    assert result["description"] == "Patient identity mapping"


def test_parse_block_tables():
    result = parse_transformation_block(SAMPLE_BLOCK)
    assert result["source_table"] == "cdm_source.axi_patient"
    assert result["dest_table"] == "omop_cdm.person"


def test_parse_block_columns():
    result = parse_transformation_block(SAMPLE_BLOCK)
    assert len(result["columns"]) == 2
    assert result["columns"][0]["source"] == "pat_id"
    assert result["columns"][0]["destination"] == "person_id"
    assert result["columns"][0]["type"] == "Long"
    assert result["columns"][0]["comment"] == "primary key"


def test_parse_block_sql():
    result = parse_transformation_block(SAMPLE_BLOCK)
    assert result["sql"] == "SELECT * FROM axi_patient"


def test_parse_block_java_class_dest():
    block = """
    <h2 id="x">1/1) Fichier 'cdm_source.biology_axi.java'</h2>
    <h4>Biology AXI</h4>
    <table><thead><tr>
        <th><em>Source</em><br/>axigate.axi_srb__t_labo_results_lar</th>
        <th><em>Destination</em><br/>class 'biology_axi' extends 'BiologyBase'</th>
        <th>Commentaires</th>
    </tr></thead><tbody></tbody></table>
    """
    result = parse_transformation_block(block)
    assert result["dest_table"] == "cdm_source.biology_axi"


# ---------------------------------------------------------------------------
# split_repertoires
# ---------------------------------------------------------------------------

def test_split_repertoires():
    html = """
    <h1 id="axigate">1/3) Repertoire 'axigate'</h1>
    <p>content A</p>
    <h1 id="cdm_source">2/3) Repertoire 'cdm_source'</h1>
    <p>content B</p>
    <h1 id="omop_cdm">3/3) Repertoire 'omop_cdm'</h1>
    <p>content C</p>
    """
    sections = split_repertoires(html)
    assert set(sections.keys()) == {"axigate", "cdm_source", "omop_cdm"}
    assert "content A" in sections["axigate"]
    assert "content B" in sections["cdm_source"]
    assert "content C" in sections["omop_cdm"]


# ---------------------------------------------------------------------------
# build_lineage (integration — uses the real HTML doc if available)
# ---------------------------------------------------------------------------

ETL_DOC_PATH = os.environ.get("ETL_DOC_PATH", os.path.join(os.path.dirname(__file__), "fixtures", "etl_doc.html"))


@pytest.fixture
def lineage_data():
    """Parse the real ETL doc (skip if not present)."""
    import os
    if not os.path.exists(ETL_DOC_PATH):
        pytest.skip("ETL doc not found")
    return build_lineage(ETL_DOC_PATH)


def test_build_lineage_metadata(lineage_data):
    meta = lineage_data["metadata"]
    assert meta["total_nodes"] > 50
    assert meta["total_edges"] > 50


def test_build_lineage_no_self_loops(lineage_data):
    for e in lineage_data["edges"]:
        assert e["source"] != e["target"], f"Self-loop: {e['source']}"


def test_build_lineage_omop_chains(lineage_data):
    chains = lineage_data["omop_chains"]
    assert "omop_cdm.person" in chains
    assert "omop_cdm.condition_occurrence" in chains
    assert "omop_cdm.measurement" in chains


def test_build_lineage_biology_chain(lineage_data):
    """Biology should have a complete chain through biology_axi/biology_cora."""
    chains = lineage_data["omop_chains"]
    measurement_chain = chains["omop_cdm.measurement"]

    # measurement ← omop_cdm.biology (which is an intermediate OMOP-layer node)
    biology_entry = next((e for e in measurement_chain if "biology" in e["from"]), None)
    assert biology_entry is not None, "biology should feed omop_cdm.measurement"

    # The biology node itself should have the inheritance edges upstream
    edges = lineage_data["edges"]
    biology_sources = [e["source"] for e in edges if e["target"] == "cdm_source.biology"]
    assert "cdm_source.biology_axi" in biology_sources
    assert "cdm_source.biology_cora" in biology_sources


def test_build_lineage_real_omop_tables_have_upstream(lineage_data):
    """Real OMOP CDM target tables should have at least one upstream source."""
    real_omop = ["omop_cdm.person", "omop_cdm.visit_occurrence",
                 "omop_cdm.condition_occurrence", "omop_cdm.measurement",
                 "omop_cdm.drug_exposure", "omop_cdm.procedure_occurrence",
                 "omop_cdm.observation", "omop_cdm.device_exposure"]
    chains = lineage_data["omop_chains"]
    for table in real_omop:
        assert table in chains, f"{table} not in omop_chains"
        assert len(chains[table]) > 0, f"{table} has no upstream chain"


def test_build_lineage_layers(lineage_data):
    """Check that nodes have valid layers."""
    valid_layers = {"source", "staging", "omop", "reference", "unknown"}
    for name, node in lineage_data["nodes"].items():
        assert node["layer"] in valid_layers, f"{name} has invalid layer: {node['layer']}"


def test_build_lineage_edges_reference_existing_nodes(lineage_data):
    """All edge endpoints should reference existing nodes."""
    nodes = lineage_data["nodes"]
    for e in lineage_data["edges"]:
        assert e["source"] in nodes, f"Edge source {e['source']} not in nodes"
        assert e["target"] in nodes, f"Edge target {e['target']} not in nodes"
