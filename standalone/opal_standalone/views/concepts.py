"""Concept explorer brick — search the OMOP vocabulary, walk the hierarchy."""
from __future__ import annotations

import streamlit as st

from opal_standalone import glue, ui
from opal_standalone.omop import connection, schema_map

TITLE = "Explorateur de concepts"
ICON = "🔎"
SUBTITLE = "Recherche dans le vocabulaire OMOP, relations, hiérarchie et valeurs source."

_PAGE_SIZE = 50


def _catalogue(cdm) -> tuple[list[str], list[str]]:
    """Vocabularies and domains present in the CDM (cached in the session)."""
    key = f"_concept_catalogue_{cdm.name}"
    if key not in st.session_state:
        try:
            with connection(cdm) as conn:
                schema = schema_map(cdm)
                st.session_state[key] = (
                    glue.list_vocabularies(conn, schema),
                    glue.list_concept_domains(conn, schema),
                )
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Catalogue indisponible ({exc}).")
            st.session_state[key] = ([], [])
    return st.session_state[key]


def _tab_search(config, cdm, store) -> None:
    vocabularies, domains = _catalogue(cdm)
    with st.form("concept_search"):
        cols = st.columns([4, 2, 2, 2])
        query = cols[0].text_input("Recherche (nom, code ou concept_id)")
        domain = cols[1].selectbox("Domaine", ["Tous"] + domains)
        vocabulary = cols[2].selectbox("Vocabulaire", ["Tous"] + vocabularies)
        standard_only = cols[3].checkbox("Standards uniquement", value=False)
        submitted = st.form_submit_button("Rechercher", type="primary")

    if submitted:
        st.session_state["concept_offset"] = 0
        st.session_state["concept_query"] = {
            "q": query,
            "domain": None if domain == "Tous" else domain,
            "vocabulary": None if vocabulary == "Tous" else vocabulary,
            "standard_only": standard_only,
        }

    params = st.session_state.get("concept_query")
    if not params:
        st.info("Lancez une recherche pour explorer le vocabulaire.")
        return

    offset = st.session_state.get("concept_offset", 0)
    try:
        with connection(cdm) as conn:
            result = glue.search_concepts(
                conn, schema_map(cdm), limit=_PAGE_SIZE, offset=offset, **params
            )
    except Exception as exc:  # noqa: BLE001
        ui.error_box(exc, "Recherche en échec")
        return

    concepts = result["concepts"]
    if concepts:
        st.caption(
            f"{result['total']} résultat(s) — affichage "
            f"{offset + 1}–{offset + len(concepts)}"
        )
    else:
        st.caption("Aucun résultat.")
    ui.show_table(concepts)
    ui.download_csv("Exporter les résultats (CSV)", concepts, "concepts.csv", key="dl_concepts")

    cols = st.columns([1, 1, 6])
    if cols[0].button("Précédent", disabled=offset == 0):
        st.session_state["concept_offset"] = max(0, offset - _PAGE_SIZE)
        st.rerun()
    if cols[1].button("Suivant", disabled=offset + _PAGE_SIZE >= result["total"]):
        st.session_state["concept_offset"] = offset + _PAGE_SIZE
        st.rerun()

    if concepts:
        labels = {
            f"{c['concept_id']} — {c['concept_name']} ({c['vocabulary_id']})": c["concept_id"]
            for c in concepts
        }
        chosen = st.selectbox("Inspecter un concept", list(labels), key="concept_pick")
        if st.button("Ouvrir le détail"):
            st.session_state["concept_detail_id"] = labels[chosen]


def _tab_detail(config, cdm, store) -> None:
    concept_id = st.number_input(
        "concept_id", min_value=0, step=1,
        value=int(st.session_state.get("concept_detail_id", 0)), key="concept_detail_input",
    )
    if not concept_id:
        st.info("Saisissez un concept_id, ou sélectionnez-en un depuis la recherche.")
        return

    try:
        with connection(cdm) as conn:
            schema = schema_map(cdm)
            details = glue.concept_details(conn, schema, int(concept_id))
            if not details:
                st.warning("Concept introuvable.")
                return
            hierarchy = glue.concept_hierarchy(conn, schema, int(concept_id))
            source_values = glue.concept_source_values(conn, schema, int(concept_id))
    except Exception as exc:  # noqa: BLE001
        ui.error_box(exc, "Chargement du concept en échec")
        return

    concept = details["concept"]
    ui.metrics([
        ("concept_id", concept["concept_id"]),
        ("Vocabulaire", concept["vocabulary_id"]),
        ("Domaine", concept["domain_id"]),
        ("Standard", concept.get("standard_concept") or "—"),
    ])
    st.markdown(f"### {concept['concept_name']}")
    st.caption(
        f"Code `{concept['concept_code']}` · classe {concept['concept_class_id']} · "
        f"valide du {concept['valid_start_date']} au {concept['valid_end_date']}"
        + (f" · invalide : {concept['invalid_reason']}" if concept.get("invalid_reason") else "")
    )

    sections = st.tabs(["Relations", "Ancêtres", "Descendants", "Valeurs source"])
    with sections[0]:
        ui.show_table(details["relationships"], empty="Aucune relation.")
    with sections[1]:
        ui.show_table(hierarchy["ancestors"], empty="Aucun ancêtre.")
    with sections[2]:
        ui.show_table(hierarchy["descendants"], empty="Aucun descendant.")
    with sections[3]:
        ui.show_table(source_values, empty="Aucune valeur source trouvée dans les tables cliniques.")
        ui.download_csv("Exporter les valeurs source (CSV)", source_values,
                        f"source_values_{concept_id}.csv", key="dl_source_values")


def render(config, cdm, store) -> None:
    ui.brick_header(TITLE, SUBTITLE, ICON)
    tabs = st.tabs(["Recherche", "Détail d'un concept"])
    with tabs[0]:
        _tab_search(config, cdm, store)
    with tabs[1]:
        _tab_detail(config, cdm, store)
