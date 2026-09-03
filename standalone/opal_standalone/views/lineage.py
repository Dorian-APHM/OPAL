"""Lineage brick — parse ETL documentation into a table-level lineage graph."""
from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from modules.lineage.parser import build_lineage
from opal_standalone import ui

TITLE = "Lineage ETL"
ICON = "🧬"
SUBTITLE = "Documentation ETL (HTML) transformée en graphe de lignage source → OMOP."

_MAX_GRAPH_EDGES = 250


def _dot(nodes: dict, edges: list[dict], focus: str | None) -> str:
    """Build a Graphviz DOT graph, optionally restricted to one table's neighbours."""
    if focus:
        kept = [e for e in edges if e.get("source") == focus or e.get("target") == focus]
    else:
        kept = edges[:_MAX_GRAPH_EDGES]
    names = {e["source"] for e in kept} | {e["target"] for e in kept}

    lines = ["digraph lineage {", "  rankdir=LR;", '  node [shape=box, style=rounded];']
    for name in sorted(names):
        layer = (nodes.get(name) or {}).get("layer", "unknown")
        lines.append(f'  "{name}" [label="{name}\\n({layer})"];')
    for edge in kept:
        label = (edge.get("transformation") or {}).get("type", "") if isinstance(
            edge.get("transformation"), dict
        ) else ""
        lines.append(f'  "{edge["source"]}" -> "{edge["target"]}" [label="{label}"];')
    lines.append("}")
    return "\n".join(lines)


def render(config, cdm, store) -> None:
    ui.brick_header(TITLE, SUBTITLE, ICON)

    uploaded = st.file_uploader("Documentation ETL (.html)", type=["html", "htm"])
    if uploaded and st.button("Analyser le document", type="primary"):
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / uploaded.name
                path.write_bytes(uploaded.read())
                graph = build_lineage(str(path))
            graph["metadata"]["source_file"] = uploaded.name
            store.save_lineage(cdm.name, uploaded.name, graph)
            st.success(
                f"{graph['metadata']['total_nodes']} tables et "
                f"{graph['metadata']['total_edges']} relations extraites."
            )
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Analyse du document en échec")

    lineage = store.get_lineage(cdm.name)
    if not lineage:
        st.info("Aucun lignage enregistré pour cette base — chargez un document ETL.")
        return

    graph = lineage["graph"]
    metadata = graph.get("metadata", {})
    ui.metrics([
        ("Tables", metadata.get("total_nodes", 0)),
        ("Relations", metadata.get("total_edges", 0)),
        ("Document", lineage["filename"]),
        ("Généré le", metadata.get("doc_date", "—")),
    ])

    nodes = graph.get("nodes", {})
    edges = graph.get("edges", [])
    tables = sorted(nodes)

    tabs = st.tabs(["Graphe", "Tables", "Relations", "Chaînes OMOP"])
    with tabs[0]:
        focus = st.selectbox("Centrer sur une table", ["— tout le graphe —"] + tables,
                             key="lineage_focus")
        st.graphviz_chart(_dot(nodes, edges, None if focus.startswith("—") else focus))
        if len(edges) > _MAX_GRAPH_EDGES and focus.startswith("—"):
            st.caption(
                f"Graphe tronqué aux {_MAX_GRAPH_EDGES} premières relations — "
                "centrez sur une table pour un rendu complet."
            )
    with tabs[1]:
        ui.show_table(list(nodes.values()))
        ui.download_csv("Exporter les tables (CSV)", list(nodes.values()), "lineage_tables.csv",
                        key="dl_lineage_nodes")
    with tabs[2]:
        rows = [
            {
                "source": e.get("source"),
                "cible": e.get("target"),
                "type": (e.get("transformation") or {}).get("type")
                if isinstance(e.get("transformation"), dict) else e.get("type"),
            }
            for e in edges
        ]
        ui.show_table(rows)
        ui.download_csv("Exporter les relations (CSV)", rows, "lineage_edges.csv",
                        key="dl_lineage_edges")
    with tabs[3]:
        chains = graph.get("omop_chains", {})
        if not chains:
            st.caption("Aucune chaîne OMOP identifiée.")
        else:
            table = st.selectbox("Table OMOP", sorted(chains), key="lineage_chain")
            st.json(chains[table], expanded=False)

    st.divider()
    cols = st.columns([2, 6])
    with cols[0]:
        if st.button("Supprimer ce lignage"):
            store.delete_lineage(cdm.name)
            st.rerun()
    with cols[1]:
        ui.download_json("Télécharger le graphe (JSON)", graph, f"lineage_{cdm.name}.json",
                         key="dl_lineage_json")
