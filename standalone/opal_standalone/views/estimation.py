"""Estimation brick — Kaplan-Meier survival curves and log-rank test."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from modules.estimation.survival import compute_km, compute_median_survival, log_rank_test
from opal_standalone import glue, ui
from opal_standalone.omop import connection, fetch_all, schema_map

TITLE = "Estimation"
ICON = "📉"
SUBTITLE = (
    "Courbes de survie Kaplan-Meier entre une cohorte cible et une cohorte "
    "évènement, avec test du log-rank."
)

_TIME_DIVISORS = {"jours": 1.0, "mois": 30.44, "années": 365.25}


def _cohort_picker(store, cdm, label: str, key: str):
    cohorts = store.list_cohorts(cdm.name)
    labels = {f"#{c['id']} {c['name']}": c["id"] for c in cohorts}
    chosen = st.selectbox(label, list(labels), key=key)
    return store.get_cohort(labels[chosen])


def _plot_curves(overall: list[dict], strata: dict[str, list[dict]], time_unit: str) -> None:
    frames = []
    if overall:
        frames.append(
            pd.DataFrame({"temps": [p["time"] for p in overall],
                          "Ensemble": [p["survival"] for p in overall]}).set_index("temps")
        )
    for name, curve in (strata or {}).items():
        frames.append(
            pd.DataFrame({"temps": [p["time"] for p in curve],
                          name: [p["survival"] for p in curve]}).set_index("temps")
        )
    if not frames:
        return
    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.join(frame, how="outer")
    merged = merged.sort_index().ffill()
    st.markdown(f"**Survie cumulée ({time_unit})**")
    st.line_chart(merged, height=340)


def _tab_compute(config, cdm, store) -> None:
    cohorts = store.list_cohorts(cdm.name)
    if len(cohorts) < 2:
        st.info(
            "Enregistrez au moins deux cohortes dans la brique « Cohortes » "
            "(la cible et l'évènement) avant d'estimer une survie."
        )
        return

    cols = st.columns(2)
    with cols[0]:
        target = _cohort_picker(store, cdm, "Cohorte cible", "km_target")
    with cols[1]:
        outcome = _cohort_picker(store, cdm, "Cohorte évènement", "km_outcome")

    cols = st.columns(3)
    time_unit = cols[0].selectbox("Unité de temps", list(_TIME_DIVISORS), index=1)
    limit_tar = cols[1].checkbox("Limiter la période à risque", value=False)
    tar_end = cols[2].number_input("Durée max (jours)", 1, 10950, 365, disabled=not limit_tar)
    strata = st.multiselect("Stratification", ["gender", "age_group"], key="km_strata")

    if st.button("Calculer la survie", type="primary"):
        try:
            schema = schema_map(cdm)
            sql = glue.kaplan_meier_sql(
                target["criteria"], outcome["criteria"], schema,
                time_at_risk_end=int(tar_end) if limit_tar else None,
                strata=strata or None,
            )
            with st.spinner("Requête en cours…"), connection(cdm) as conn:
                rows = fetch_all(conn, sql)
            if not rows:
                st.warning("Aucun patient à risque pour ces cohortes.")
                return

            divisor = _TIME_DIVISORS[time_unit]
            times = [float(r["time_days"]) / divisor for r in rows]
            events = [int(r["had_event"]) for r in rows]
            overall = compute_km(times, events)
            median = compute_median_survival(overall)

            strata_curves: dict[str, list[dict]] = {}
            lr_test = None
            if strata:
                column = "gender_name" if "gender" in strata else strata[0]
                groups: dict[str, tuple[list, list]] = {}
                for row, time, event in zip(rows, times, events):
                    key = str(row.get(column, "Unknown"))
                    groups.setdefault(key, ([], []))
                    groups[key][0].append(time)
                    groups[key][1].append(event)
                strata_curves = {k: compute_km(t, e) for k, (t, e) in sorted(groups.items())}
                lr_test = log_rank_test(groups)

            st.session_state["km_result"] = {
                "target_name": target["name"],
                "outcome_name": outcome["name"],
                "overall": overall,
                "strata": strata_curves,
                "log_rank": lr_test,
                "median_survival": round(median, 2) if median is not None else None,
                "time_unit": time_unit,
                "summary": {
                    "n": len(rows),
                    "events": sum(events),
                    "censored": len(rows) - sum(events),
                },
                "sql": sql,
            }
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Estimation en échec")

    result = st.session_state.get("km_result")
    if not result:
        return

    summary = result["summary"]
    ui.metrics([
        ("Patients", ui.fmt_int(summary["n"])),
        ("Évènements", ui.fmt_int(summary["events"])),
        ("Censurés", ui.fmt_int(summary["censored"])),
        ("Survie médiane", result["median_survival"] if result["median_survival"] is not None else "non atteinte"),
    ])
    _plot_curves(result["overall"], result.get("strata") or {}, result["time_unit"])

    if result.get("log_rank"):
        st.markdown("**Test du log-rank**")
        st.json(result["log_rank"], expanded=False)

    with st.expander("Table de survie"):
        ui.show_table(result["overall"])
        ui.download_csv("Exporter la courbe (CSV)", result["overall"], "kaplan_meier.csv",
                        key="dl_km")
    with st.expander("SQL exécuté"):
        st.code(result.get("sql", ""), language="sql")

    name = st.text_input("Nom de l'analyse à enregistrer", key="km_name")
    if st.button("Enregistrer l'analyse", disabled=not name):
        store.save_analysis(
            "estimation", cdm.name, name,
            {
                "target": result["target_name"],
                "outcome": result["outcome_name"],
                "time_unit": result["time_unit"],
            },
            result,
        )
        st.success("Analyse enregistrée.")


def _tab_history(config, cdm, store) -> None:
    analyses = store.list_analyses("estimation", cdm.name)
    if not analyses:
        st.info("Aucune analyse enregistrée.")
        return
    labels = {f"#{a['id']} {a['name']} ({a['created_at']})": a["id"] for a in analyses}
    chosen = st.selectbox("Analyse", list(labels), key="km_history")
    analysis = store.get_analysis(labels[chosen])
    if st.button("Supprimer", key="km_delete"):
        store.delete_analysis(analysis["id"])
        st.rerun()
    result = analysis["results"]
    _plot_curves(result.get("overall") or [], result.get("strata") or {},
                 result.get("time_unit", "jours"))
    ui.download_json("Télécharger l'analyse (JSON)", analysis, f"estimation_{analysis['id']}.json",
                     key="dl_km_json")


def render(config, cdm, store) -> None:
    ui.brick_header(TITLE, SUBTITLE, ICON)
    tabs = st.tabs(["Calcul", "Historique"])
    with tabs[0]:
        _tab_compute(config, cdm, store)
    with tabs[1]:
        _tab_history(config, cdm, store)
