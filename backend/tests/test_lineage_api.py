"""Tests for Lineage API endpoints."""
import io
import pytest


MINIMAL_ETL_HTML = """<!DOCTYPE html>
<html><body>
<h2>Documentation générée le 2025-03-15</h2>
<h3>Test Author</h3>
<h1 id="axigate">1/2) Repertoire 'axigate'</h1>
<h2 id="t1">1/1) Fichier 'axigate.src_table.java'</h2>
<h4>Source extraction</h4>
<table>
    <thead><tr>
        <th><em>Source</em><br/>src_db.src_table</th>
        <th><em>Destination</em><br/>axigate.src_table</th>
        <th>Commentaires</th>
    </tr></thead>
    <tbody>
        <tr><td>col_a</td><td>col_a (String)</td><td></td></tr>
    </tbody>
</table>
<h1 id="omop_cdm">2/2) Repertoire 'omop_cdm'</h1>
<h2 id="t2">1/1) Fichier 'omop_cdm._010_src_to_person.java'</h2>
<h4>Person mapping</h4>
<table>
    <thead><tr>
        <th><em>Source</em><br/>axigate.src_table</th>
        <th><em>Destination</em><br/>omop_cdm.person</th>
        <th>Commentaires</th>
    </tr></thead>
    <tbody>
        <tr><td>col_a</td><td>person_id (Long) PK</td><td>primary key</td></tr>
    </tbody>
</table>
</body></html>
"""


def _upload_lineage(client, cdm_name="test_cdm", html=MINIMAL_ETL_HTML):
    """Helper: upload a lineage doc."""
    return client.post(
        "/api/lineage/upload",
        data={"cdm_name": cdm_name},
        files={"file": ("etl.html", io.BytesIO(html.encode()), "text/html")},
    )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def test_upload_lineage(client):
    resp = _upload_lineage(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["cdm_name"] == "test_cdm"
    assert body["metadata"]["total_nodes"] > 0
    assert body["metadata"]["total_edges"] > 0


def test_upload_replaces_existing(client):
    _upload_lineage(client, "cdm1")
    resp = _upload_lineage(client, "cdm1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_upload_rejects_non_html(client):
    resp = client.post(
        "/api/lineage/upload",
        data={"cdm_name": "test"},
        files={"file": ("data.csv", io.BytesIO(b"a,b,c"), "text/csv")},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Get lineage
# ---------------------------------------------------------------------------

def test_get_lineage(client):
    _upload_lineage(client, "cdm2")
    resp = client.get("/api/lineage/cdm2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cdm_name"] == "cdm2"
    assert "nodes" in body["lineage"]
    assert "edges" in body["lineage"]
    assert "omop_chains" in body["lineage"]


def test_get_lineage_not_found(client):
    resp = client.get("/api/lineage/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def test_get_summary(client):
    _upload_lineage(client, "cdm3")
    resp = client.get("/api/lineage/cdm3/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_nodes"] > 0
    assert body["total_edges"] > 0
    assert "omop" in body["layers"]
    assert "omop_cdm.person" in body["omop_tables"]


def test_summary_not_found(client):
    resp = client.get("/api/lineage/nope/summary")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# OMOP chains
# ---------------------------------------------------------------------------

def test_get_omop_chains(client):
    _upload_lineage(client, "cdm4")
    resp = client.get("/api/lineage/cdm4/omop-chains")
    assert resp.status_code == 200
    chains = resp.json()["chains"]
    assert "omop_cdm.person" in chains


def test_get_omop_chains_single_table(client):
    _upload_lineage(client, "cdm5")
    resp = client.get("/api/lineage/cdm5/omop-chains", params={"table": "person"})
    assert resp.status_code == 200
    assert resp.json()["table"] == "omop_cdm.person"
    assert len(resp.json()["chain"]) > 0


def test_get_omop_chains_unknown_table(client):
    _upload_lineage(client, "cdm6")
    resp = client.get("/api/lineage/cdm6/omop-chains", params={"table": "nonexistent"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_delete_lineage(client):
    _upload_lineage(client, "cdm7")
    resp = client.delete("/api/lineage/cdm7")
    assert resp.status_code == 200

    resp = client.get("/api/lineage/cdm7")
    assert resp.status_code == 404


def test_delete_not_found(client):
    resp = client.delete("/api/lineage/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Parsed content validation
# ---------------------------------------------------------------------------

def test_parsed_nodes_have_correct_layers(client):
    _upload_lineage(client, "cdm8")
    resp = client.get("/api/lineage/cdm8")
    nodes = resp.json()["lineage"]["nodes"]
    for name, node in nodes.items():
        if name.startswith("omop_cdm."):
            assert node["layer"] == "omop"
        elif name.startswith("axigate."):
            assert node["layer"] == "source"


def test_parsed_edges_have_column_mappings(client):
    _upload_lineage(client, "cdm9")
    resp = client.get("/api/lineage/cdm9")
    edges = resp.json()["lineage"]["edges"]
    # The omop_cdm edge should have column mappings
    omop_edges = [e for e in edges if e["target"].startswith("omop_cdm.")]
    assert len(omop_edges) > 0
    assert len(omop_edges[0]["column_mappings"]) > 0


def test_chain_traces_full_path(client):
    """OMOP chain should trace back through source layer."""
    _upload_lineage(client, "cdm10")
    resp = client.get("/api/lineage/cdm10/omop-chains", params={"table": "person"})
    chain = resp.json()["chain"]
    # person ← axigate.src_table ← src_db.src_table
    assert chain[0]["from"] == "axigate.src_table"
    upstream = chain[0].get("upstream", [])
    assert len(upstream) > 0
    assert upstream[0]["from"] == "src_db.src_table"
