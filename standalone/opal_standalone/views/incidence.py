"""Incidence brick — incidence rate of an outcome cohort in a target cohort."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from modules.incidence.engine import build_incidence_sql, compute_incidence
from opal_standalone import glue, ui
from opal_standalone.omop import connection, fetch_all, schema_map

TITLE = "Incidence"
ICON = "📈"
SUBTITLE = (
    "Taux d'incidence et proportion, avec intervalle de confiance de Poisson, "
    "à partir de deux cohortes enregistrées (cible et évènement)."
)

_DEFAULT_AGE_GROUPS = [
    {"min": 0, "max": 17, "label": "0-17"},
    {"min": 18, "max": 39, "label": "18-39"},
    {"min": 40, "max": 64, "label": "40-64"},
    {"min": 65, "max": 200, "label": "65+"},
]


def _cohort_picker(store, cdm, label: str, key: str):
    cohorts = store.list_cohorts(cdm.name)
    if not cohorts:
        return None
    labels = {f"#{c['id']} {c['name']}": c["id"] for c in cohorts}
    chosen = st.selectbox(label, list(labels), key=key)
    return store.get_cohort(labels[chosen])


def _tab_compute(config, cdm, store) -> None:
    cohorts = store.list_cohorts(cdm.name)
    if len(cohorts) < 2:
        st.info(
            "Enregistrez au moins deux cohortes dans la brique « Cohortes » "
            "(la cible et l'évènement) avant de calculer une incidence."
        )
        return

    cols = st.columns(2)
    with cols[0]:
        target = _cohort_picker(store, cdm, "Cohorte cible", "inc_target")
    with cols[1]:
        outcome = _cohort_picker(store, cdm, "Cohorte évènement", "inc_outcome")
    if not target or not outcome:
        return

    cols = st.columns(4)
    tar_start = cols[0].number_input("Début de la période à risque (jours)", 0, 3650, 0)
    tar_end_mode = cols[1].selectbox("Fin de la période à risque", ["Fin d'observation", "Durée fixe"])
    tar_end_days = cols[2].number_input(
        "Durée (jours)", 1, 10950, 365, disabled=tar_end_mode == "Fin d'observation"
    )
    clean_window = cols[3].number_input("Fenêtre d'exclusion antérieure (jours)", 0, 3650, 0)

    strata = st.multiselect(
        "Stratification", ["gender_name", "age_group", "calendar_year"], key="inc_strata"
    )
    age_groups = _DEFAULT_AGE_GROUPS if "age_group" in strata else []

    if st.button("Calculer l'incidence", type="primary"):
        try:
            schema = schema_map(cdm)
            sql = build_incidence_sql(
                target_sql=glue.dated_cohort_sql(target["criteria"], schema),
                outcome_sql=glue.dated_cohort_sql(outcome["criteria"], schema),
                omop_schema=schema,
                time_at_risk_start=int(tar_start),
                time_at_risk_end=(
                    "observation_end" if tar_end_mode == "Fin d'observation" else int(tar_end_days)
                ),
                strata=strata,
                age_groups=age_groups,
                clean_window=int(clean_window),
            )
            with st.spinner("Requête en cours…"), connection(cdm) as conn:
                rows = fetch_all(conn, sql)
            result = compute_incidence(rows, strata=strata, age_groups=age_groups or None)
            result["target_name"] = target["name"]
            result["outcome_name"] = outcome["name"]
            result["sql"] = sql
            st.session_state["incidence_result"] = result
            st.session_state["incidence_params"] = {
                "target_cohort": target["name"],
                "outcome_cohort": outcome["name"],
                "time_at_risk_start": int(tar_start),
                "time_at_risk_end": (
                    "observation_end" if tar_end_mode == "Fin d'observation" else int(tar_end_days)
                ),
                "clean_window": int(clean_window),
                "strata": strata,
            }
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Calcul d'incidence en échec")

    result = st.session_state.get("incidence_result")
    if not result:
        return

    ui.metrics([
        ("Cohorte cible", ui.fmt_int(result.get("target_count"))),
        ("Évènements", ui.fmt_int(result.get("outcome_count"))),
        ("Personnes-années", ui.fmt_int(round(result.get("person_years") or 0))),
        ("Taux /1000 PA", round(result.get("incidence_rate") or 0, 2)),
        ("Proportion (%)", round((result.get("incidence_proportion") or 0), 2)),
    ])
    st.caption(
        f"IC 95 % du taux : {round(result.get('ci_lower') or 0, 2)} – "
        f"{round(result.get('ci_upper') or 0, 2)}"
    )

    strata_rows = result.get("strata") or []
    if strata_rows:
        flat = []
        for row in strata_rows:
            entry = dict(row.get("strata_values") or {})
            entry.update({
                k: v for k, v in row.items() if k not in ("strata_values", "strata")
            })
            flat.append(entry)
        st.markdown("**Résultats par strate**")
        ui.show_table(flat)
        frame = pd.DataFrame(flat)
        label_col = next((c for c in frame.columns if c in
                          ("gender_name", "age_group", "calendar_year")), None)
        if label_col and "incidence_rate" in frame.columns:
            st.bar_chart(frame[[label_col, "incidence_rate"]].set_index(label_col), height=260)
        ui.download_csv("Exporter les strates (CSV)", flat, "incidence_strata.csv",
                        key="dl_inc_strata")

    with st.expander("SQL exécuté"):
        st.code(result.get("sql", ""), language="sql")

    name = st.text_input("Nom de l'analyse à enregistrer", key="inc_name")
    if st.button("Enregistrer l'analyse", disabled=not name):
        store.save_analysis(
            "incidence", cdm.name, name,
            st.session_state.get("incidence_params", {}), result,
        )
        st.success("Analyse enregistrée.")


def _tab_history(config, cdm, store) -> None:
    analyses = store.list_analyses("incidence", cdm.name)
    if not analyses:
        st.info("Aucune analyse enregistrée.")
        return
    labels = {f"#{a['id']} {a['name']} ({a['created_at']})": a["id"] for a in analyses}
    chosen = st.selectbox("Analyse", list(labels), key="inc_history")
    analysis = store.get_analysis(labels[chosen])
    cols = st.columns([2, 6])
    if cols[0].button("Supprimer", key="inc_delete"):
        store.delete_analysis(analysis["id"])
        st.rerun()
    st.json(analysis["parameters"], expanded=False)
    result = analysis["results"]
    ui.metrics([
        ("Cohorte cible", ui.fmt_int(result.get("target_count"))),
        ("Évènements", ui.fmt_int(result.get("outcome_count"))),
        ("Taux /1000 PA", round(result.get("incidence_rate") or 0, 2)),
    ])
    ui.download_json("Télécharger l'analyse (JSON)", analysis, f"incidence_{analysis['id']}.json",
                     key="dl_inc_json")


def render(config, cdm, store) -> None:
    ui.brick_header(TITLE, SUBTITLE, ICON)
    tabs = st.tabs(["Calcul", "Historique"])
    with tabs[0]:
        _tab_compute(config, cdm, store)
    with tabs[1]:
        _tab_history(config, cdm, store)
