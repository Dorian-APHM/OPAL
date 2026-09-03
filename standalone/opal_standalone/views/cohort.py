"""Cohort brick — build a definition, count it, characterise it, walk its pathways.

The SQL is produced by ``modules.cohort.sql_builder`` (the exact builder the
server uses), characterisation by ``modules.cohort.characterization`` and
treatment pathways by ``modules.cohort.pathways``. Definitions are saved in the
local SQLite store.
"""
from __future__ import annotations

import json
import uuid

import pandas as pd
import streamlit as st

from config import DOMAIN_CONFIG
from modules.cohort.characterization import run_characterization
from modules.cohort.comparison import compare_cohorts
from modules.cohort.pathways import run_pathways_analysis
from modules.cohort.sql_builder import (
    build_attrition_sql,
    build_cohort_sql,
    build_count_sql,
    build_detailed_sample_sql,
    build_export_sql,
)
from opal_standalone import glue, ui
from opal_standalone.omop import connection, fetch_all, fetch_one, schema_map

TITLE = "Cohortes"
ICON = "👥"
SUBTITLE = (
    "Constructeur de cohortes OMOP : critères, attrition, échantillon, "
    "caractérisation (Table 1), parcours de soins et comparaison."
)

_STATE = "cohort_criteria"
_GENDER_CONCEPTS = {"Femme (8532)": 8532, "Homme (8507)": 8507}
_OCCURRENCE_TYPES = ["any", "at_least", "at_most", "exactly"]


def _empty_criteria() -> dict:
    return {
        "inclusion": {"operator": "AND", "criteria": [], "sameVisit": False},
        "exclusion": {"operator": "OR", "criteria": []},
        "demographics": {},
    }


def _criteria() -> dict:
    if _STATE not in st.session_state:
        st.session_state[_STATE] = _empty_criteria()
    return st.session_state[_STATE]


def _set_criteria(criteria: dict) -> None:
    st.session_state[_STATE] = criteria


def _parse_ids(raw: str) -> list[int]:
    ids = []
    for token in raw.replace(";", ",").replace("\n", ",").split(","):
        token = token.strip()
        if token:
            ids.append(int(token))
    return ids


def _parse_codes(raw: str) -> list[str]:
    return [t.strip() for t in raw.replace(";", ",").replace("\n", ",").split(",") if t.strip()]


def _criterion_summary(criterion: dict) -> str:
    parts = [criterion.get("domain", "?")]
    concepts = criterion.get("concepts", [])
    if concepts:
        parts.append(f"{len(concepts)} concept(s)")
    codes = criterion.get("source_codes", [])
    if codes:
        parts.append(f"{len(codes)} code(s) source")
    occurrence = criterion.get("occurrence", {})
    if occurrence.get("type") and occurrence["type"] != "any":
        parts.append(f"{occurrence['type']} {occurrence.get('count', 1)}")
    temporal = criterion.get("temporal", {})
    if temporal.get("type") == "absolute_window":
        parts.append(f"{temporal.get('date_from', '…')} → {temporal.get('date_to', '…')}")
    return " · ".join(parts)


# ── criteria editor ──────────────────────────────────────────────────────

def _criterion_form(store, cdm, group_key: str) -> None:
    concept_sets = store.list_concept_sets(cdm.name)
    with st.form(f"add_{group_key}", clear_on_submit=True):
        cols = st.columns([2, 2, 2])
        domain = cols[0].selectbox("Domaine", sorted(DOMAIN_CONFIG), key=f"dom_{group_key}")
        set_names = ["— aucun —"] + [cs["name"] for cs in concept_sets]
        chosen_set = cols[1].selectbox("Depuis un concept set", set_names, key=f"cs_{group_key}")
        include_descendants = cols[2].checkbox(
            "Inclure les descendants", value=True, key=f"desc_{group_key}"
        )

        concepts_raw = st.text_input(
            "concept_id (séparés par des virgules)", key=f"cids_{group_key}"
        )
        codes_raw = st.text_input(
            "Codes source (source_value / ATC, séparés par des virgules)",
            key=f"codes_{group_key}",
        )

        cols = st.columns(4)
        occurrence_type = cols[0].selectbox("Occurrence", _OCCURRENCE_TYPES, key=f"occ_{group_key}")
        occurrence_count = cols[1].number_input(
            "Nombre", min_value=1, value=1, step=1, key=f"occn_{group_key}"
        )
        date_from = cols[2].text_input("Date min (AAAA-MM-JJ)", key=f"df_{group_key}")
        date_to = cols[3].text_input("Date max (AAAA-MM-JJ)", key=f"dt_{group_key}")

        value_operator = value_number = None
        if domain == "Measurement":
            cols = st.columns(2)
            value_operator = cols[0].selectbox(
                "Valeur", ["—", ">", ">=", "<", "<=", "="], key=f"vop_{group_key}"
            )
            value_number = cols[1].number_input("Seuil", value=0.0, key=f"vnum_{group_key}")

        if st.form_submit_button("Ajouter le critère"):
            concepts = [{"concept_id": cid} for cid in _parse_ids(concepts_raw)]
            codes = _parse_codes(codes_raw)
            if chosen_set != "— aucun —":
                payload = next(cs["payload"] for cs in concept_sets if cs["name"] == chosen_set)
                concepts += [
                    {"concept_id": int(c["concept_id"])} for c in payload.get("concepts", [])
                ]
                codes += [str(c) for c in payload.get("source_codes", [])]
            if not concepts and not codes:
                st.warning("Indiquez au moins un concept_id ou un code source.")
                return

            criterion = {
                "id": uuid.uuid4().hex[:8],
                "domain": domain,
                "concepts": concepts,
                "source_codes": codes,
                "include_descendants": include_descendants,
            }
            if occurrence_type != "any":
                criterion["occurrence"] = {"type": occurrence_type, "count": int(occurrence_count)}
            if date_from or date_to:
                criterion["temporal"] = {
                    "type": "absolute_window",
                    "date_from": date_from or None,
                    "date_to": date_to or None,
                }
            if value_operator and value_operator != "—":
                criterion["value"] = {"operator": value_operator, "value": float(value_number)}

            _criteria()[group_key]["criteria"].append(criterion)
            st.rerun()


def _group_editor(store, cdm, group_key: str, label: str) -> None:
    criteria = _criteria()
    group = criteria[group_key]
    st.markdown(f"**{label}**")
    operator = st.radio(
        "Opérateur", ["AND", "OR"],
        index=0 if group.get("operator", "AND") == "AND" else 1,
        horizontal=True, key=f"op_{group_key}",
    )
    group["operator"] = operator
    if group_key == "inclusion":
        group["sameVisit"] = st.checkbox(
            "Tous les critères sur le même séjour (same visit)",
            value=bool(group.get("sameVisit")), key="same_visit",
        )

    for index, criterion in enumerate(list(group["criteria"])):
        cols = st.columns([8, 1])
        cols[0].caption(f"{index + 1}. {_criterion_summary(criterion)}")
        if cols[1].button("✕", key=f"del_{group_key}_{index}"):
            group["criteria"].pop(index)
            st.rerun()
    if not group["criteria"]:
        st.caption("Aucun critère.")

    with st.expander(f"Ajouter un critère ({label.lower()})"):
        _criterion_form(store, cdm, group_key)


def _demographics_editor() -> None:
    demographics = _criteria().setdefault("demographics", {})
    st.markdown("**Démographie**")
    cols = st.columns([2, 1, 1, 2])
    genders = cols[0].multiselect(
        "Genre", list(_GENDER_CONCEPTS),
        default=[k for k, v in _GENDER_CONCEPTS.items() if v in (demographics.get("gender") or [])],
        key="demo_gender",
    )
    age_min = cols[1].number_input(
        "Âge min", min_value=0, max_value=120,
        value=int((demographics.get("age") or {}).get("min") or 0), key="demo_age_min",
    )
    age_max = cols[2].number_input(
        "Âge max", min_value=0, max_value=120,
        value=int((demographics.get("age") or {}).get("max") or 120), key="demo_age_max",
    )
    at_index = cols[3].checkbox(
        "Âge à la date index", value=(demographics.get("age") or {}).get("at") == "index",
        key="demo_age_at_index",
    )

    demographics.clear()
    if genders:
        demographics["gender"] = [_GENDER_CONCEPTS[g] for g in genders]
    if age_min > 0 or age_max < 120:
        demographics["age"] = {"min": int(age_min), "max": int(age_max)}
        if at_index:
            demographics["age"]["at"] = "index"


def _tab_definition(config, cdm, store) -> None:
    saved = store.list_cohorts(cdm.name)
    cols = st.columns([3, 2, 2])
    with cols[0]:
        labels = ["— nouvelle cohorte —"] + [f"#{c['id']} {c['name']}" for c in saved]
        chosen = st.selectbox("Cohorte enregistrée", labels, key="cohort_pick")
    with cols[1]:
        st.write("")
        if st.button("Charger", disabled=chosen == labels[0], use_container_width=True):
            cohort_id = int(chosen.split()[0].lstrip("#"))
            cohort = store.get_cohort(cohort_id)
            _set_criteria(cohort["criteria"])
            st.session_state["cohort_current_id"] = cohort_id
            st.session_state["cohort_name"] = cohort["name"]
            st.rerun()
    with cols[2]:
        st.write("")
        if st.button("Supprimer", disabled=chosen == labels[0], use_container_width=True):
            store.delete_cohort(int(chosen.split()[0].lstrip("#")))
            st.session_state.pop("cohort_current_id", None)
            st.rerun()

    st.divider()
    _demographics_editor()
    st.divider()
    _group_editor(store, cdm, "inclusion", "Critères d'inclusion")
    st.divider()
    _group_editor(store, cdm, "exclusion", "Critères d'exclusion")

    st.divider()
    cols = st.columns([3, 2, 2])
    name = cols[0].text_input("Nom de la cohorte", key="cohort_name")
    description = cols[1].text_input("Description", key="cohort_description")
    cols[2].write("")
    if cols[2].button("Enregistrer", type="primary", disabled=not name, use_container_width=True):
        try:
            glue.validate_criteria(_criteria())
        except ValueError as exc:
            st.error(f"Définition invalide : {exc}")
        else:
            cohort_id = store.save_cohort(
                cdm.name, name, _criteria(), description,
                cohort_id=st.session_state.get("cohort_current_id"),
            )
            st.session_state["cohort_current_id"] = cohort_id
            st.success(f"Cohorte enregistrée (#{cohort_id}).")

    with st.expander("Définition JSON (édition avancée)"):
        raw = st.text_area(
            "criteria", json.dumps(_criteria(), indent=2, ensure_ascii=False),
            height=280, key="cohort_json",
        )
        if st.button("Appliquer le JSON"):
            try:
                parsed = glue.validate_criteria(json.loads(raw))
            except (ValueError, json.JSONDecodeError) as exc:
                st.error(f"JSON invalide : {exc}")
            else:
                _set_criteria(parsed)
                st.success("Définition mise à jour.")
                st.rerun()

    with st.expander("SQL généré"):
        try:
            st.code(build_cohort_sql(_criteria(), schema_map(cdm)), language="sql")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Impossible de générer le SQL : {exc}")


# ── counts / attrition / sample ──────────────────────────────────────────

def _tab_counts(config, cdm, store) -> None:
    criteria = _criteria()
    if not criteria["inclusion"]["criteria"]:
        st.info("Ajoutez au moins un critère d'inclusion.")
        return
    schema = schema_map(cdm)

    if st.button("Compter les patients", type="primary"):
        try:
            with connection(cdm) as conn:
                row = fetch_one(conn, build_count_sql(criteria, schema))
            st.session_state["cohort_count"] = int(row["patient_count"]) if row else 0
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Comptage en échec")

    if "cohort_count" in st.session_state:
        ui.metrics([("Patients dans la cohorte", ui.fmt_int(st.session_state["cohort_count"]))])

    st.divider()
    st.markdown("**Attrition** — effectif après ajout de chaque critère")
    if st.button("Calculer l'attrition"):
        try:
            steps = build_attrition_sql(criteria, schema)
            results = []
            progress = st.progress(0.0)
            with connection(cdm) as conn:
                for index, step in enumerate(steps):
                    progress.progress(index / max(len(steps), 1), text=step["label"])
                    row = fetch_one(conn, step["sql"])
                    count = int(list(row.values())[0]) if row else 0
                    results.append({"étape": step["label"], "patients": count})
            progress.empty()
            for index, row in enumerate(results):
                previous = results[index - 1]["patients"] if index else None
                row["retenus (%)"] = (
                    round(row["patients"] / previous * 100, 2) if previous else 100.0
                )
            st.session_state["cohort_attrition"] = results
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Attrition en échec")

    attrition = st.session_state.get("cohort_attrition")
    if attrition:
        ui.show_table(attrition)
        st.bar_chart(pd.DataFrame(attrition).set_index("étape")["patients"], height=280)
        ui.download_csv("Exporter l'attrition (CSV)", attrition, "attrition.csv", key="dl_attrition")


def _tab_sample(config, cdm, store) -> None:
    criteria = _criteria()
    if not criteria["inclusion"]["criteria"]:
        st.info("Ajoutez au moins un critère d'inclusion.")
        return
    schema = schema_map(cdm)

    limit = st.slider("Taille de l'échantillon", 5, 200, 20, 5)
    if st.button("Tirer un échantillon", type="primary"):
        try:
            sql, columns_meta = build_detailed_sample_sql(criteria, schema, limit=limit)
            with connection(cdm) as conn:
                rows = fetch_all(conn, sql)
            st.session_state["cohort_sample"] = rows
            st.session_state["cohort_sample_meta"] = columns_meta
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Échantillon en échec")

    rows = st.session_state.get("cohort_sample")
    if rows:
        meta = st.session_state.get("cohort_sample_meta") or []
        if meta:
            with st.expander("Colonnes dynamiques"):
                ui.show_table(meta)
        ui.show_table(rows)
        ui.download_csv("Exporter l'échantillon (CSV)", rows, "cohort_sample.csv", key="dl_sample")

    st.divider()
    st.markdown("**Export complet de la cohorte**")
    st.caption("Exporte l'ensemble des person_id et dates de la cohorte (peut être volumineux).")
    if st.button("Préparer l'export"):
        try:
            with connection(cdm) as conn:
                rows = fetch_all(conn, build_export_sql(criteria, schema))
            st.session_state["cohort_export"] = rows
            st.success(f"{len(rows)} lignes prêtes.")
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Export en échec")
    if st.session_state.get("cohort_export"):
        ui.download_csv(
            "Télécharger la cohorte (CSV)", st.session_state["cohort_export"],
            "cohort.csv", key="dl_cohort_export",
        )


# ── characterization / pathways / comparison ─────────────────────────────

def _render_characterization(result: dict) -> None:
    demographics = result.get("demographics", {})
    age = demographics.get("age") or {}
    ui.metrics([
        ("Patients", ui.fmt_int(result.get("cohort_size"))),
        ("Âge moyen", round(age["mean_age"], 1) if age.get("mean_age") is not None else "—"),
        ("Niveau séjour", "oui" if result.get("visit_level") else "non"),
    ])

    for key, label in (("gender", "Genre"), ("age_groups", "Tranches d'âge"),
                       ("race", "Race"), ("ethnicity", "Ethnicité")):
        rows = demographics.get(key)
        if rows:
            st.markdown(f"**{label}**")
            ui.show_table(rows)

    prevalence = result.get("domain_prevalence") or []
    if prevalence:
        st.markdown("**Prévalence par domaine**")
        ui.show_table(
            [{k: v for k, v in row.items() if k != "top_concepts"} for row in prevalence]
        )
        for row in prevalence:
            concepts = row.get("top_concepts") or []
            if concepts:
                with st.expander(f"Concepts les plus fréquents — {row.get('domain')}"):
                    ui.show_table(concepts)

    for key, label in (("measurement_stats", "Mesures"), ("visit_types", "Types de séjour")):
        rows = result.get(key)
        if rows:
            st.markdown(f"**{label}**")
            ui.show_table(rows)

    for key, label in (("observation_period", "Période d'observation"),
                       ("visit_duration", "Durée des séjours")):
        block = result.get(key)
        if block:
            with st.expander(label):
                st.json(block, expanded=False)


def _tab_characterization(config, cdm, store) -> None:
    criteria = _criteria()
    if not criteria["inclusion"]["criteria"]:
        st.info("Ajoutez au moins un critère d'inclusion.")
        return

    cols = st.columns([2, 2, 3])
    top_n = cols[0].number_input("Top N par domaine", 5, 100, 20, 5)
    visit_level = cols[1].checkbox(
        "Restreindre au séjour qualifiant", value=False,
        help="Nécessite l'option « same visit » sur les critères d'inclusion.",
    )
    if cols[2].button("Lancer la caractérisation", type="primary"):
        progress = st.progress(0.0, text="Préparation…")

        def _on_progress(completed, total, label):
            progress.progress(min(completed / max(total, 1), 1.0), text=label)

        try:
            # Characterization builds a session scratch table (as on the server),
            # so this connection is opened without the read-only session switch.
            with connection(cdm, allow_temp_tables=True) as conn:
                result = run_characterization(
                    conn, criteria, schema_map(cdm), top_n=int(top_n),
                    visit_level=visit_level, progress_callback=_on_progress,
                )
            st.session_state["cohort_characterization"] = result
            cohort_id = st.session_state.get("cohort_current_id")
            if cohort_id:
                store.set_cohort_result(cohort_id, "characterization", result)
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Caractérisation en échec")
        finally:
            progress.empty()

    result = st.session_state.get("cohort_characterization")
    if result:
        _render_characterization(result)
        ui.download_json("Télécharger la caractérisation (JSON)", result,
                         "characterization.json", key="dl_char")


def _tab_pathways(config, cdm, store) -> None:
    criteria = _criteria()
    if not criteria["inclusion"]["criteria"]:
        st.info("Ajoutez au moins un critère d'inclusion pour la cohorte cible.")
        return

    st.caption(
        "Parcours de soins façon ATLAS : la cohorte cible ci-dessus, puis un ou "
        "plusieurs « évènements » définis par des concept_id."
    )
    events = st.session_state.setdefault("pathway_events", [])
    with st.form("add_event", clear_on_submit=True):
        cols = st.columns([3, 2, 4, 2])
        name = cols[0].text_input("Nom de l'évènement")
        domain = cols[1].selectbox("Domaine", sorted(DOMAIN_CONFIG))
        concept_ids = cols[2].text_input("concept_id (virgules)")
        descendants = cols[3].checkbox("Descendants", value=True)
        if st.form_submit_button("Ajouter l'évènement") and name and concept_ids:
            events.append({
                "name": name,
                "domain": domain,
                "concept_ids": _parse_ids(concept_ids),
                "include_descendants": descendants,
            })
            st.rerun()

    for index, event in enumerate(list(events)):
        cols = st.columns([8, 1])
        cols[0].caption(
            f"{index + 1}. {event['name']} — {event['domain']}, "
            f"{len(event['concept_ids'])} concept(s)"
        )
        if cols[1].button("✕", key=f"del_event_{index}"):
            events.pop(index)
            st.rerun()

    cols = st.columns(3)
    max_depth = cols[0].number_input("Profondeur max", 1, 10, 3)
    min_cell = cols[1].number_input("Effectif minimal par parcours", 1, 1000, 5)
    combo_window = cols[2].number_input("Fenêtre de combinaison (jours)", 0, 365, 30)

    if st.button("Lancer l'analyse de parcours", type="primary", disabled=not events):
        progress = st.progress(0.0, text="Préparation…")

        def _on_progress(completed, total, label):
            progress.progress(min(completed / max(total, 1), 1.0), text=label)

        try:
            # Pathways builds session scratch tables and drops them at the end.
            with connection(cdm, allow_temp_tables=True) as conn:
                result = run_pathways_analysis(
                    conn, criteria, events, schema_map(cdm),
                    max_depth=int(max_depth), min_cell_count=int(min_cell),
                    combo_window=int(combo_window), progress_callback=_on_progress,
                )
            st.session_state["cohort_pathways"] = result
            cohort_id = st.session_state.get("cohort_current_id")
            if cohort_id:
                store.set_cohort_result(cohort_id, "pathways", result)
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Analyse de parcours en échec")
        finally:
            progress.empty()

    result = st.session_state.get("cohort_pathways")
    if not result:
        return

    ui.metrics([
        ("Cohorte cible", ui.fmt_int(result.get("target_size"))),
        ("Patients avec parcours", ui.fmt_int(result.get("persons_with_pathways"))),
    ])
    table = result.get("pathways_table", [])
    if table:
        ui.show_table(table)
        ui.download_csv("Exporter les parcours (CSV)", table, "pathways.csv", key="dl_pathways")
    _render_sunburst(result.get("sunburst_tree"))


def _render_sunburst(tree: dict | None) -> None:
    if not tree:
        return
    try:
        import plotly.graph_objects as go
    except ImportError:
        st.caption("Installez `plotly` pour afficher le diagramme sunburst.")
        return

    labels, parents, values = [], [], []

    def _walk(node: dict, parent_id: str, path: str) -> None:
        for child in node.get("children", []) or []:
            node_id = f"{path}/{child.get('name', '?')}"
            labels.append(child.get("name", "?"))
            parents.append(parent_id)
            values.append(child.get("count", 0))
            _walk(child, node_id, node_id)

    labels.append("Cohorte")
    parents.append("")
    values.append(tree.get("count", 0))
    _walk(tree, "Cohorte", "Cohorte")
    if len(labels) <= 1:
        return
    figure = go.Figure(
        go.Sunburst(labels=labels, parents=parents, values=values, branchvalues="total")
    )
    figure.update_layout(margin=dict(t=10, l=0, r=0, b=0), height=520)
    st.plotly_chart(figure, use_container_width=True)


def _tab_compare(config, cdm, store) -> None:
    cohorts = store.list_cohorts(cdm.name)
    with_char = []
    for cohort in cohorts:
        full = store.get_cohort(cohort["id"])
        if full and full.get("characterization"):
            with_char.append(full)
    if len(with_char) < 2:
        st.info(
            "Comparez deux cohortes enregistrées et caractérisées "
            "(onglet « Caractérisation », après avoir enregistré la cohorte)."
        )
        return

    labels = {f"#{c['id']} {c['name']}": c for c in with_char}
    cols = st.columns(2)
    label_a = cols[0].selectbox("Cohorte A", list(labels), key="cmp_a")
    label_b = cols[1].selectbox("Cohorte B", list(labels), index=1, key="cmp_b")
    if label_a == label_b:
        st.warning("Sélectionnez deux cohortes différentes.")
        return

    result = compare_cohorts(
        labels[label_a]["characterization"], labels[label_b]["characterization"]
    )
    ui.metrics([
        (f"{labels[label_a]['name']} (A)", ui.fmt_int(result.get("cohort_a_size"))),
        (f"{labels[label_b]['name']} (B)", ui.fmt_int(result.get("cohort_b_size"))),
    ])
    st.caption("Une SMD supérieure à 0,1 signale un déséquilibre entre les deux cohortes.")

    all_vars = result.get("all_variables") or []
    if all_vars:
        st.markdown("**Différences standardisées (SMD)**")
        only_imbalanced = st.checkbox("N'afficher que les SMD > 0,1", value=False, key="cmp_smd")
        rows = [
            row for row in all_vars
            if not only_imbalanced or abs(row.get("smd") or 0) > 0.1
        ]
        ui.show_table(rows)
        ui.download_csv("Exporter les SMD (CSV)", all_vars, "cohort_smd.csv", key="dl_smd")

    demographics = result.get("demographics") or {}
    for key, label in (("gender", "Genre"), ("age_groups", "Tranches d'âge"),
                       ("race", "Race"), ("ethnicity", "Ethnicité")):
        rows = demographics.get(key)
        if rows:
            with st.expander(f"Démographie — {label}"):
                ui.show_table(rows)

    for key, label in (("domain_prevalence", "Prévalence par domaine"),
                       ("measurement_stats", "Mesures"), ("visit_types", "Types de séjour")):
        rows = result.get(key)
        if rows:
            with st.expander(label):
                ui.show_table(
                    [{k: v for k, v in row.items() if k != "concepts"} for row in rows]
                )

    ui.download_json("Télécharger la comparaison (JSON)", result, "cohort_comparison.json",
                     key="dl_cohort_cmp")


def _tab_sql(config, cdm, store) -> None:
    st.caption(
        "Console SQL en lecture seule (SELECT / WITH / EXPLAIN uniquement, "
        "session PostgreSQL forcée en lecture seule)."
    )
    default = ""
    try:
        if _criteria()["inclusion"]["criteria"]:
            default = build_cohort_sql(_criteria(), schema_map(cdm))
    except Exception:  # noqa: BLE001 - the editor stays usable regardless
        default = ""
    sql = st.text_area("Requête", default, height=260, key="cohort_sql_text")
    limit = st.number_input("Limite de lignes", 10, 5000, 100, 10)
    if st.button("Exécuter", type="primary"):
        try:
            with connection(cdm) as conn:
                rows = glue.run_read_only_sql(conn, sql, limit=int(limit))
            st.session_state["cohort_sql_rows"] = rows
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Requête en échec")
    rows = st.session_state.get("cohort_sql_rows")
    if rows is not None:
        st.caption(f"{len(rows)} ligne(s)")
        ui.show_table(rows)
        ui.download_csv("Exporter le résultat (CSV)", rows, "query_result.csv", key="dl_sql")


def render(config, cdm, store) -> None:
    ui.brick_header(TITLE, SUBTITLE, ICON)
    tabs = st.tabs([
        "Définition", "Effectifs & attrition", "Échantillon",
        "Caractérisation", "Parcours", "Comparaison", "SQL",
    ])
    with tabs[0]:
        _tab_definition(config, cdm, store)
    with tabs[1]:
        _tab_counts(config, cdm, store)
    with tabs[2]:
        _tab_sample(config, cdm, store)
    with tabs[3]:
        _tab_characterization(config, cdm, store)
    with tabs[4]:
        _tab_pathways(config, cdm, store)
    with tabs[5]:
        _tab_compare(config, cdm, store)
    with tabs[6]:
        _tab_sql(config, cdm, store)
