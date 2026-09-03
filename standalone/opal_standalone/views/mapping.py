"""Mapping brick — unmapped source terms, suggestions, local decisions.

Suggestions come from ``modules.mapping.suggest``: the three deterministic SQL
strategies (exact code, OMOP "Maps to" relationship, ingredient/galenic form).
SapBERT is a separate service in the server deployment and is not part of the
standalone bricks, so it is simply absent here — the other strategies are
unaffected. Decisions are stored locally and can be exported as a
``source_to_concept_map`` CSV; the standalone apps never write to the CDM.
"""
from __future__ import annotations

import io
import csv

import streamlit as st

from modules.mapping.suggest import suggest_batch, suggest_mappings
from opal_standalone import glue, ui
from opal_standalone.omop import connection, schema_map
from utils.csv_safety import csv_safe

TITLE = "Mapping"
ICON = "🔗"
SUBTITLE = (
    "Termes source non mappés, suggestions de concepts standards et décisions "
    "de mapping conservées localement."
)


def _domains(cdm) -> list[str]:
    key = f"_mapping_domains_{cdm.name}"
    if key not in st.session_state:
        try:
            with connection(cdm) as conn:
                st.session_state[key] = glue.mappable_domains(conn, schema_map(cdm))
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Domaines indisponibles ({exc}).")
            st.session_state[key] = []
    return st.session_state[key]


def _strategy_toggles() -> dict:
    cols = st.columns(3)
    return {
        "enable_exact": cols[0].checkbox("Code exact", value=True, key="map_exact"),
        "enable_relationship": cols[1].checkbox("Relation « Maps to »", value=True, key="map_rel"),
        "enable_ingredient": cols[2].checkbox("Ingrédient / forme galénique", value=True,
                                              key="map_ing"),
    }


def _tab_dashboard(config, cdm, store) -> None:
    domains = _domains(cdm)
    if not domains:
        st.info("Aucun domaine clinique exploitable dans ce CDM.")
        return
    chosen = st.multiselect("Domaines", domains, default=domains[:4], key="map_dash_domains")
    if st.button("Calculer la couverture", type="primary", disabled=not chosen):
        rows = []
        progress = st.progress(0.0)
        try:
            with connection(cdm) as conn:
                schema = schema_map(cdm)
                for index, domain in enumerate(chosen):
                    progress.progress(index / len(chosen), text=domain)
                    summary = glue.mapping_summary(conn, schema, domain)
                    if summary:
                        rows.append(summary)
            st.session_state["mapping_summary"] = rows
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Calcul de couverture en échec")
        finally:
            progress.empty()

    rows = st.session_state.get("mapping_summary")
    if rows:
        ui.show_table(rows)
        import pandas as pd

        st.bar_chart(
            pd.DataFrame(rows)[["domain", "pct_terms_mapped"]].set_index("domain"),
            height=260,
        )
        ui.download_csv("Exporter la couverture (CSV)", rows, "mapping_coverage.csv",
                        key="dl_map_cov")


def _tab_workbench(config, cdm, store) -> None:
    domains = _domains(cdm)
    if not domains:
        st.info("Aucun domaine clinique exploitable dans ce CDM.")
        return

    cols = st.columns([2, 3, 2])
    domain = cols[0].selectbox("Domaine", domains, key="map_domain")
    search = cols[1].text_input("Filtrer les termes", key="map_search")
    limit = cols[2].number_input("Nombre de termes", 10, 1000, 100, 10, key="map_limit")

    if st.button("Charger les termes non mappés", type="primary"):
        try:
            with connection(cdm) as conn:
                st.session_state["mapping_terms"] = glue.unmapped_terms(
                    conn, schema_map(cdm), domain, limit=int(limit), search=search
                )
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Chargement des termes en échec")

    terms = st.session_state.get("mapping_terms") or []
    if not terms:
        st.caption("Aucun terme chargé.")
        return

    decisions = {d["source_value"]: d for d in store.list_decisions(cdm.name, domain)}
    ui.show_table([
        {
            **term,
            "décision": decisions.get(term["source_value"], {}).get("status", "—"),
            "concept retenu": decisions.get(term["source_value"], {}).get("target_concept_id") or "",
        }
        for term in terms
    ], height=280)

    st.divider()
    labels = {
        f"{t['source_value']} — {t.get('source_name') or ''} ({t['n_records']} lignes)": t
        for t in terms
    }
    chosen = st.selectbox("Terme à traiter", list(labels), key="map_term")
    term = labels[chosen]
    toggles = _strategy_toggles()
    max_suggestions = st.slider("Suggestions", 1, 20, 5, key="map_max")

    if st.button("Proposer des concepts"):
        try:
            with connection(cdm) as conn:
                st.session_state["mapping_suggestions"] = suggest_mappings(
                    conn, term["source_value"], term.get("source_name"), domain,
                    schema_map(cdm), max_suggestions=int(max_suggestions), **toggles,
                )
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Suggestions en échec")

    suggestions = st.session_state.get("mapping_suggestions") or []
    if suggestions:
        ui.show_table(suggestions)
        options = {
            f"{s['concept_id']} — {s.get('concept_name')} "
            f"({s.get('strategy')}, {s.get('confidence')})": s
            for s in suggestions
        }
        picked = st.selectbox("Concept retenu", list(options), key="map_pick")
        comment = st.text_input("Commentaire", key="map_comment")
        cols = st.columns([2, 2, 6])
        if cols[0].button("Accepter", type="primary"):
            suggestion = options[picked]
            store.save_decision(cdm.name, domain, {
                "source_value": term["source_value"],
                "source_name": term.get("source_name"),
                "target_concept_id": suggestion["concept_id"],
                "target_concept_name": suggestion.get("concept_name"),
                "status": "accepted",
                "strategy": suggestion.get("strategy"),
                "confidence": suggestion.get("confidence"),
                "comment": comment,
            })
            st.success(f"Mapping enregistré pour « {term['source_value']} ».")
        if cols[1].button("Rejeter le terme"):
            store.save_decision(cdm.name, domain, {
                "source_value": term["source_value"],
                "source_name": term.get("source_name"),
                "status": "rejected",
                "comment": comment,
            })
            st.info("Terme marqué comme rejeté.")

    st.divider()
    st.markdown("**Suggestions en lot**")
    batch_size = st.slider("Nombre de termes à traiter", 5, 200, 25, 5, key="map_batch_size")
    if st.button("Générer les suggestions en lot"):
        progress = st.progress(0.0, text="Analyse…")
        try:
            with connection(cdm) as conn:
                results = suggest_batch(
                    conn, terms[: int(batch_size)], domain, schema_map(cdm),
                    max_per_term=3, **toggles,
                )
            st.session_state["mapping_batch"] = [
                {
                    "source_value": row["source_value"],
                    "source_name": row.get("source_name"),
                    "suggestions": len(row["suggestions"]),
                    "meilleur concept": (row["suggestions"] or [{}])[0].get("concept_id"),
                    "nom": (row["suggestions"] or [{}])[0].get("concept_name"),
                    "stratégie": (row["suggestions"] or [{}])[0].get("strategy"),
                    "confiance": (row["suggestions"] or [{}])[0].get("confidence"),
                }
                for row in results
            ]
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Suggestions en lot en échec")
        finally:
            progress.empty()

    batch = st.session_state.get("mapping_batch")
    if batch:
        ui.show_table(batch)
        ui.download_csv("Exporter les suggestions (CSV)", batch, "mapping_suggestions.csv",
                        key="dl_map_batch")
        if st.button("Accepter toutes les suggestions de confiance ≥ 90"):
            accepted = 0
            for row in batch:
                if (row.get("confiance") or 0) >= 90 and row.get("meilleur concept"):
                    store.save_decision(cdm.name, domain, {
                        "source_value": row["source_value"],
                        "source_name": row.get("source_name"),
                        "target_concept_id": row["meilleur concept"],
                        "target_concept_name": row.get("nom"),
                        "status": "accepted",
                        "strategy": row.get("stratégie"),
                        "confidence": row.get("confiance"),
                    })
                    accepted += 1
            st.success(f"{accepted} mapping(s) enregistré(s).")


def _source_to_concept_map_csv(cdm_name: str, decisions: list[dict]) -> str:
    """Export accepted decisions in OMOP ``source_to_concept_map`` column order."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "source_code", "source_concept_id", "source_vocabulary_id", "source_code_description",
        "target_concept_id", "target_vocabulary_id", "valid_start_date", "valid_end_date",
        "invalid_reason",
    ])
    for decision in decisions:
        if decision.get("status") != "accepted" or not decision.get("target_concept_id"):
            continue
        writer.writerow([
            csv_safe(decision["source_value"]), 0, csv_safe(f"{cdm_name}_{decision['domain']}"),
            csv_safe(decision.get("source_name") or ""), decision["target_concept_id"], "",
            "1970-01-01", "2099-12-31", "",
        ])
    return output.getvalue()


def _tab_decisions(config, cdm, store) -> None:
    decisions = store.list_decisions(cdm.name)
    if not decisions:
        st.info("Aucune décision enregistrée.")
        return
    ui.metrics([
        ("Décisions", len(decisions)),
        ("Acceptées", sum(1 for d in decisions if d["status"] == "accepted")),
        ("Rejetées", sum(1 for d in decisions if d["status"] == "rejected")),
    ])
    ui.show_table(decisions)
    cols = st.columns(3)
    with cols[0]:
        ui.download_csv("Exporter les décisions (CSV)", decisions, "mapping_decisions.csv",
                        key="dl_decisions")
    with cols[1]:
        st.download_button(
            "Exporter en source_to_concept_map (CSV)",
            _source_to_concept_map_csv(cdm.name, decisions).encode("utf-8"),
            file_name=f"source_to_concept_map_{cdm.name}.csv", mime="text/csv",
            key="dl_stcm",
        )
    with cols[2]:
        ids = {f"#{d['id']} {d['source_value']}": d["id"] for d in decisions}
        chosen = st.selectbox("Supprimer une décision", list(ids), key="del_decision")
        if st.button("Supprimer"):
            store.delete_decision(ids[chosen])
            st.rerun()


def render(config, cdm, store) -> None:
    ui.brick_header(TITLE, SUBTITLE, ICON)
    tabs = st.tabs(["Couverture", "Atelier de mapping", "Décisions"])
    with tabs[0]:
        _tab_dashboard(config, cdm, store)
    with tabs[1]:
        _tab_workbench(config, cdm, store)
    with tabs[2]:
        _tab_decisions(config, cdm, store)
