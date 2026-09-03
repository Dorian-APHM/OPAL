"""Data management brick — extract a cohort's raw OMOP rows as CSV.

Uses ``modules.datamanagement.extractor``: the same table list, the same SQL and
the same relational schema description as the server, packaged as a ZIP the
browser downloads directly (no task queue, no temporary server storage).
"""
from __future__ import annotations

import csv
import io
import zipfile

import streamlit as st

from modules.cohort.sql_builder import build_cohort_sql
from modules.datamanagement.extractor import (
    build_schema,
    build_table_sql,
    get_table_columns,
    list_available_tables,
)
from opal_standalone import ui
from opal_standalone.omop import connection, schema_map
from utils.csv_safety import csv_safe

TITLE = "Data management"
ICON = "📦"
SUBTITLE = "Extraction des données OMOP d'une cohorte, table par table, en CSV."

_FETCH_SIZE = 5000


def _cohort_has_same_visit(criteria: dict) -> bool:
    return bool(criteria.get("inclusion", {}).get("sameVisit", False))


def _tables(cdm) -> list[str]:
    key = f"_dm_tables_{cdm.name}"
    if key not in st.session_state:
        try:
            with connection(cdm) as conn:
                st.session_state[key] = list_available_tables(conn, schema_map(cdm))
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Tables indisponibles ({exc}).")
            st.session_state[key] = []
    return st.session_state[key]


def _columns(cdm, table: str) -> list[dict]:
    key = f"_dm_columns_{cdm.name}_{table}"
    if key not in st.session_state:
        try:
            with connection(cdm) as conn:
                st.session_state[key] = get_table_columns(conn, schema_map(cdm), table)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Colonnes indisponibles pour {table} ({exc}).")
            st.session_state[key] = []
    return st.session_state[key]


def _extract_zip(cdm, cohort_sql: str, selections: list[dict], same_visit_only: bool,
                 cohort_has_visit: bool) -> tuple[bytes, list[dict]]:
    """Run one extraction query per table and pack the CSVs into a ZIP."""
    buffer = io.BytesIO()
    report: list[dict] = []
    schema = schema_map(cdm)
    progress = st.progress(0.0, text="Extraction…")
    try:
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive, connection(cdm) as conn:
            for index, selection in enumerate(selections):
                table = selection["table"]
                progress.progress(index / len(selections), text=f"Table {table}…")
                sql = build_table_sql(
                    cohort_sql, schema, table, selection["columns"],
                    same_visit_only, cohort_has_visit,
                )
                text = io.StringIO()
                writer = csv.writer(text)
                writer.writerow(selection["columns"])
                rows = 0
                with conn.cursor(name=f"opal_extract_{table}") as cur:
                    cur.itersize = _FETCH_SIZE
                    cur.execute(sql)
                    for row in cur:
                        writer.writerow([csv_safe(value) for value in row])
                        rows += 1
                archive.writestr(f"{table}.csv", text.getvalue())
                report.append({"table": table, "lignes": rows, "colonnes": len(selection["columns"])})
        progress.progress(1.0, text="Terminé")
    finally:
        progress.empty()
    return buffer.getvalue(), report


def render(config, cdm, store) -> None:
    ui.brick_header(TITLE, SUBTITLE, ICON)

    cohorts = store.list_cohorts(cdm.name)
    if not cohorts:
        st.info("Enregistrez d'abord une cohorte dans la brique « Cohortes ».")
        return

    labels = {f"#{c['id']} {c['name']}": c["id"] for c in cohorts}
    chosen = st.selectbox("Cohorte à extraire", list(labels), key="dm_cohort")
    cohort = store.get_cohort(labels[chosen])
    has_visit = _cohort_has_same_visit(cohort["criteria"])

    tables = _tables(cdm)
    if not tables:
        return
    selected_tables = st.multiselect(
        "Tables", tables, default=[t for t in ("person", "visit_occurrence") if t in tables],
        key="dm_tables",
    )

    selections: list[dict] = []
    all_columns: dict[str, list[dict]] = {}
    for table in selected_tables:
        columns = _columns(cdm, table)
        all_columns[table] = columns
        names = [c["column_name"] for c in columns]
        with st.expander(f"Colonnes — {table} ({len(names)})"):
            chosen_columns = st.multiselect(
                "Colonnes exportées", names, default=names, key=f"dm_cols_{table}"
            )
        if chosen_columns:
            selections.append({"table": table, "columns": chosen_columns})

    same_visit_only = st.checkbox(
        "Restreindre aux séjours qualifiants", value=False, disabled=not has_visit,
        help="Disponible uniquement si la cohorte utilise l'option « same visit ».",
    )

    if selections:
        with st.expander("Schéma relationnel des tables sélectionnées"):
            description = build_schema(selections, all_columns)
            ui.show_table(
                [
                    {
                        "table": t["name"],
                        "clé primaire": t.get("pk"),
                        "colonnes sélectionnées": sum(
                            1 for c in t["columns"] if c.get("selected")
                        ),
                    }
                    for t in description["tables"]
                ]
            )
            ui.show_table(description["relationships"], empty="Aucune relation.")

    if st.button("Lancer l'extraction", type="primary", disabled=not selections):
        try:
            cohort_sql = build_cohort_sql(
                cohort["criteria"], schema_map(cdm), include_visit_id=has_visit
            )
            payload, report = _extract_zip(
                cdm, cohort_sql, selections, same_visit_only, has_visit
            )
            st.session_state["dm_zip"] = payload
            st.session_state["dm_report"] = report
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Extraction en échec")

    if st.session_state.get("dm_zip"):
        ui.show_table(st.session_state.get("dm_report") or [])
        st.download_button(
            "Télécharger l'extraction (ZIP)", st.session_state["dm_zip"],
            file_name=f"extraction_{cdm.name}_{cohort['name']}.zip",
            mime="application/zip", type="primary", key="dl_extract",
        )
