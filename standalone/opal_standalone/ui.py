"""Shared Streamlit chrome for the standalone bricks."""
from __future__ import annotations

import io
import json
import traceback
from typing import Iterable, Sequence

import pandas as pd
import streamlit as st

from opal_standalone.config import AppConfig, CdmConnection, ConfigError, load_config
from opal_standalone.omop import connection, test_connection
from opal_standalone.store import Store

BRICKS = [
    ("quality", "Qualité", "🔍", "Analyses Achilles-like, conformité, snapshots, rapports"),
    ("cohort", "Cohortes", "👥", "Constructeur de cohortes, attrition, caractérisation, parcours"),
    ("concepts", "Concepts", "🔎", "Exploration du vocabulaire OMOP"),
    ("concept_sets", "Concept sets", "🧩", "Ensembles de concepts et de codes source"),
    ("mapping", "Mapping", "🔗", "Termes non mappés et suggestions de concepts"),
    ("incidence", "Incidence", "📈", "Taux d'incidence sur cohortes cible/évènement"),
    ("estimation", "Estimation", "📉", "Courbes de survie Kaplan-Meier et log-rank"),
    ("datamanagement", "Data management", "📦", "Extraction de données par cohorte"),
    ("lineage", "Lineage ETL", "🧬", "Documentation ETL parsée en graphe de lignage"),
]


@st.cache_resource(show_spinner=False)
def get_config() -> AppConfig:
    return load_config()


@st.cache_resource(show_spinner=False)
def get_store(path: str) -> Store:
    return Store(path)


def page_setup(title: str, icon: str = "🩺") -> None:
    st.set_page_config(page_title=f"OPAL — {title}", page_icon=icon, layout="wide")


def config_or_stop() -> AppConfig:
    """Load the configuration, or show actionable instructions and stop."""
    try:
        return get_config()
    except ConfigError as exc:
        st.error("Configuration OPAL standalone introuvable ou invalide.")
        st.code(str(exc), language="text")
        st.markdown(
            "Copiez `standalone/config.example.toml` vers `standalone/config.toml`, "
            "renseignez la connexion OMOP, puis rechargez la page."
        )
        st.stop()


def sidebar(active: str) -> tuple[AppConfig, CdmConnection, Store]:
    """Render the common sidebar and return (config, selected CDM, store)."""
    config = config_or_stop()
    store = get_store(str(config.storage_path))

    with st.sidebar:
        st.markdown("### OPAL standalone")
        names = config.names
        if len(names) > 1:
            selected = st.selectbox("Base OMOP", names, key="_opal_cdm")
        else:
            selected = names[0]
            st.caption(f"Base OMOP : **{selected}**")
        cdm = config.cdm(selected)
        st.caption(f"`{cdm.user}@{cdm.host}:{cdm.port}/{cdm.database}` — schéma `{cdm.schema}`")

        if st.button("Tester la connexion", use_container_width=True):
            try:
                info = test_connection(cdm)
                st.success(
                    f"OK — PostgreSQL {info['server_version'].split()[1]}, "
                    f"{info['tables_in_schema']} tables dans `{info['schema']}`"
                    + (f", {info['persons']:,} patients".replace(",", " ") if info["persons"] is not None else "")
                )
            except Exception as exc:  # noqa: BLE001 - surfaced to the user
                st.error(f"Connexion impossible : {exc}")

        st.divider()
        st.caption("Briques disponibles")
        for key, label, icon, _desc in BRICKS:
            marker = "▸ " if key == active else "　"
            st.caption(f"{marker}{icon} {label}" + ("  ← ici" if key == active else ""))
        st.caption(
            "Chaque brique se lance seule :\n\n"
            "`streamlit run standalone/apps/<brique>.py`"
        )

        st.divider()
        if st.button("Recharger la configuration", use_container_width=True):
            get_config.clear()
            st.rerun()
        if config.source_path:
            st.caption(f"Config : `{config.source_path}`")
        st.caption(f"Données locales : `{store.path}`")

    return config, cdm, store


def cdm_connection(cdm: CdmConnection):
    """Context manager for a CDM connection (re-exported for the views)."""
    return connection(cdm)


def dataframe(rows: Iterable[dict], columns: Sequence[str] | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows))
    if columns and not frame.empty:
        keep = [c for c in columns if c in frame.columns]
        frame = frame[keep + [c for c in frame.columns if c not in keep]]
    return frame


def show_table(rows: Iterable[dict], *, columns: Sequence[str] | None = None,
               empty: str = "Aucune donnée.", height: int | None = None) -> pd.DataFrame:
    frame = dataframe(rows, columns)
    if frame.empty:
        st.caption(empty)
        return frame
    extra = {"height": height} if height else {}
    st.dataframe(frame, use_container_width=True, hide_index=True, **extra)
    return frame


def download_csv(label: str, rows: Iterable[dict], filename: str, *, key: str | None = None) -> None:
    frame = dataframe(rows)
    if frame.empty:
        return
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    st.download_button(
        label, buffer.getvalue().encode("utf-8"), file_name=filename,
        mime="text/csv", key=key,
    )


def download_json(label: str, payload, filename: str, *, key: str | None = None) -> None:
    st.download_button(
        label,
        json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8"),
        file_name=filename,
        mime="application/json",
        key=key,
    )


def error_box(exc: Exception, context: str = "") -> None:
    """Show an exception without leaking a stack trace into the main flow."""
    st.error(f"{context + ' : ' if context else ''}{exc}")
    with st.expander("Détails techniques"):
        st.code("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))


def metrics(items: Sequence[tuple[str, object]], *, columns: int | None = None) -> None:
    """Render a row of metrics from (label, value) pairs."""
    items = [item for item in items if item is not None]
    if not items:
        return
    cols = st.columns(columns or len(items))
    for col, (label, value) in zip(cols, items):
        col.metric(label, value)


def fmt_int(value) -> str:
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def fmt_pct(value, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f} %"
    except (TypeError, ValueError):
        return "—"


def brick_header(title: str, subtitle: str, icon: str = "") -> None:
    st.title(f"{icon} {title}".strip())
    st.caption(subtitle)
