"""Concept set brick — reusable sets of OMOP concepts and/or source codes.

Sets are stored locally and consumed by the cohort builder: a concept set feeds
``concepts`` criteria, a source-code set feeds ``source_codes`` criteria.
"""
from __future__ import annotations

import json

import streamlit as st

from opal_standalone import glue, ui
from opal_standalone.omop import connection, schema_map

TITLE = "Concept sets"
ICON = "🧩"
SUBTITLE = "Ensembles de concepts OMOP et de codes source, réutilisables dans les cohortes."


def _parse_ids(raw: str) -> list[int]:
    return [int(t.strip()) for t in raw.replace(";", ",").replace("\n", ",").split(",") if t.strip()]


def _parse_codes(raw: str) -> list[str]:
    return [t.strip() for t in raw.replace(";", ",").replace("\n", ",").split(",") if t.strip()]


def _editor(config, cdm, store) -> None:
    sets = store.list_concept_sets(cdm.name)
    labels = ["— nouveau —"] + [f"#{s['id']} {s['name']}" for s in sets]
    chosen = st.selectbox("Concept set", labels, key="cs_pick")

    current = None
    if chosen != labels[0]:
        current = store.get_concept_set(int(chosen.split()[0].lstrip("#")))

    payload = (current or {}).get("payload", {}) if current else {}
    name = st.text_input("Nom", value=(current or {}).get("name", ""), key="cs_name")
    description = st.text_input(
        "Description", value=(current or {}).get("description", ""), key="cs_desc"
    )
    concepts_raw = st.text_area(
        "concept_id (virgules)",
        value=", ".join(str(c["concept_id"]) for c in payload.get("concepts", [])),
        key="cs_concepts", height=90,
    )
    codes_raw = st.text_area(
        "Codes source (virgules)",
        value=", ".join(str(c) for c in payload.get("source_codes", [])),
        key="cs_codes", height=90,
    )
    include_descendants = st.checkbox(
        "Inclure les descendants lors de la résolution",
        value=bool(payload.get("include_descendants", True)), key="cs_desc_flag",
    )

    cols = st.columns([2, 2, 6])
    if cols[0].button("Enregistrer", type="primary", disabled=not name):
        new_payload = {
            "concepts": [
                {"concept_id": cid, "include_descendants": include_descendants}
                for cid in _parse_ids(concepts_raw)
            ],
            "source_codes": _parse_codes(codes_raw),
            "include_descendants": include_descendants,
        }
        store.save_concept_set(
            cdm.name, name, new_payload, description,
            concept_set_id=current["id"] if current else None,
        )
        st.success("Concept set enregistré.")
        st.rerun()
    if cols[1].button("Supprimer", disabled=current is None):
        store.delete_concept_set(current["id"])
        st.rerun()

    if current:
        st.divider()
        st.markdown("**Résolution et volumétrie**")
        if st.button("Résoudre dans la base OMOP"):
            try:
                with connection(cdm) as conn:
                    schema = schema_map(cdm)
                    resolved = glue.resolve_concepts(conn, schema, payload.get("concepts", []))
                    counts = glue.concept_counts(conn, schema, resolved)
                st.session_state["cs_resolved"] = {"ids": resolved, "counts": counts}
            except Exception as exc:  # noqa: BLE001
                ui.error_box(exc, "Résolution en échec")

        resolved = st.session_state.get("cs_resolved")
        if resolved:
            ui.metrics([
                ("Concepts résolus", ui.fmt_int(len(resolved["ids"]))),
                ("Domaines avec données", len(resolved["counts"])),
            ])
            ui.show_table(resolved["counts"], empty="Aucun enregistrement pour ces concepts.")
            ui.download_json("Télécharger les concept_id résolus", resolved["ids"],
                             f"{current['name']}_resolved.json", key="dl_resolved")


def _library(config, cdm, store) -> None:
    sets = store.list_concept_sets(cdm.name)
    if not sets:
        st.info("Aucun concept set enregistré.")
    else:
        ui.show_table([
            {
                "id": s["id"],
                "nom": s["name"],
                "description": s["description"],
                "concepts": len(s["payload"].get("concepts", [])),
                "codes source": len(s["payload"].get("source_codes", [])),
                "modifié": s["updated_at"],
            }
            for s in sets
        ])
        ui.download_json("Exporter la bibliothèque (JSON)", sets, "concept_sets.json",
                         key="dl_cs_library")

    st.divider()
    st.markdown("**Importer**")
    uploaded = st.file_uploader("Fichier JSON exporté depuis OPAL", type=["json"], key="cs_import")
    if uploaded and st.button("Importer"):
        try:
            data = json.loads(uploaded.read().decode("utf-8"))
            entries = data if isinstance(data, list) else [data]
            for entry in entries:
                store.save_concept_set(
                    cdm.name,
                    entry.get("name", "import"),
                    entry.get("payload") or entry.get("concepts_json") or {},
                    entry.get("description", ""),
                )
            st.success(f"{len(entries)} concept set(s) importé(s).")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Import en échec")


def render(config, cdm, store) -> None:
    ui.brick_header(TITLE, SUBTITLE, ICON)
    tabs = st.tabs(["Éditeur", "Bibliothèque"])
    with tabs[0]:
        _editor(config, cdm, store)
    with tabs[1]:
        _library(config, cdm, store)
