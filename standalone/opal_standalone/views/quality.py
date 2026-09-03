"""Quality brick — Achilles-like analyses, conformity, snapshots and reports.

Runs the very analyses the server runs (``modules.quality.*``); results are
versioned in the local SQLite store instead of the application database.
"""
from __future__ import annotations

import csv
import io
import re

import pandas as pd
import streamlit as st

from modules.quality.comparator import compare_snapshots
from modules.quality.conformity import run_conformity_checks
from modules.quality.engine import get_available_domains, run_domain_analysis
from modules.quality.report_builder import build_comparison_html_report, build_html_report
from opal_standalone import ui
from opal_standalone.omop import connection, schema_map
from utils.csv_safety import csv_safe

TITLE = "Qualité"
ICON = "🔍"
SUBTITLE = (
    "Analyses Achilles-like par domaine, conformité CDM, historique versionné "
    "et rapports — sans serveur ni base applicative."
)


# ── helpers ──────────────────────────────────────────────────────────────

def _available_domains(cdm) -> list[str]:
    """Domains offered by this CDM (cached in the session, refreshable)."""
    key = f"_quality_domains_{cdm.name}"
    if key not in st.session_state:
        try:
            with connection(cdm) as conn:
                st.session_state[key] = get_available_domains(conn, schema_map(cdm))
        except Exception as exc:  # noqa: BLE001 - shown to the user
            st.warning(f"Domaines listés hors connexion ({exc}).")
            st.session_state[key] = get_available_domains()
    return st.session_state[key]


def _analysis_kwargs(config) -> dict:
    params = config.analysis
    return {
        "top_unmapped": params.top_unmapped_terms,
        "top_concepts": params.top_concepts,
        "max_records_per_person": params.max_records_per_person,
        "max_observation_months": params.max_observation_months,
    }


def _run_analyses(cdm, store, config, domains: list[str]) -> list[dict]:
    """Run each domain analysis and persist a snapshot; returns the snapshots."""
    schema = schema_map(cdm)
    kwargs = _analysis_kwargs(config)
    saved: list[dict] = []
    progress = st.progress(0.0, text="Connexion à la base OMOP…")
    try:
        with connection(cdm) as conn:
            for index, domain in enumerate(domains):
                progress.progress(index / len(domains), text=f"Analyse de « {domain} »…")
                try:
                    results = run_domain_analysis(conn, domain, omop_schema=schema, **kwargs)
                except Exception as exc:  # noqa: BLE001 - one domain must not stop the batch
                    conn.rollback()
                    st.error(f"Domaine « {domain} » en échec : {exc}")
                    continue
                saved.append(store.save_snapshot(cdm.name, domain, results))
        progress.progress(1.0, text="Terminé")
    finally:
        progress.empty()
    return saved


# ── result renderers (one per domain family) ─────────────────────────────

def _render_dashboard(results: dict) -> None:
    summary = results.get("summary", {})
    domains = summary.get("domains", [])
    ui.metrics([
        ("Patients", ui.fmt_int(summary.get("total_persons"))),
        ("Domaines analysés", len(domains)),
        ("Enregistrements", ui.fmt_int(sum(d.get("total_records", 0) for d in domains))),
    ])
    if not domains:
        st.caption("Aucun domaine trouvé dans ce CDM.")
        return

    frame = pd.DataFrame(domains)
    display = frame.drop(columns=[c for c in ("sparkline",) if c in frame.columns])
    st.dataframe(display, use_container_width=True, hide_index=True)
    chart = frame[["domain", "pct_terms_mapped"]].set_index("domain")
    st.markdown("**Termes mappés par domaine (%)**")
    st.bar_chart(chart, height=260)
    st.markdown("**Volumétrie par domaine**")
    st.bar_chart(frame[["domain", "total_records"]].set_index("domain"), height=260)
    ui.download_csv("Exporter les statistiques (CSV)", domains, "dashboard_domains.csv",
                    key="dl_dashboard")


def _render_person(results: dict) -> None:
    summary = results.get("achilles_like", {}).get("person_summary", {})
    ui.metrics([("Patients", ui.fmt_int(summary.get("total_persons")))])

    gender = summary.get("gender_distribution", {})
    if gender.get("gender_name"):
        st.markdown("**Répartition par genre**")
        frame = pd.DataFrame(
            {"genre": gender["gender_name"], "patients": gender["count"]}
        ).set_index("genre")
        st.bar_chart(frame, height=240)

    births = summary.get("birth_year_distribution", {})
    if births.get("year_of_birth"):
        st.markdown("**Année de naissance**")
        frame = pd.DataFrame(
            {"année": births["year_of_birth"], "patients": births["count"]}
        ).set_index("année")
        st.line_chart(frame, height=240)

    for key, label, name_key in (
        ("race_distribution", "Race", "race_name"),
        ("ethnicity_distribution", "Ethnicité", "ethnicity_name"),
    ):
        block = summary.get(key, {})
        if block.get(name_key):
            with st.expander(label):
                ui.show_table(
                    [
                        {label: n, "patients": c}
                        for n, c in zip(block[name_key], block["count"])
                    ]
                )


def _render_observation_period(results: dict) -> None:
    achilles = results.get("achilles_like", {})

    age = achilles.get("age_at_first_observation", {})
    if age.get("age"):
        st.markdown("**Âge à la première période d'observation**")
        st.bar_chart(
            pd.DataFrame({"âge": age["age"], "patients": age["count"]}).set_index("âge"),
            height=240,
        )

    length = achilles.get("observation_length_months", {})
    if length.get("months"):
        st.markdown(
            f"**Durée d'observation (mois, plafonnée à {length.get('cap_months', '—')})**"
        )
        st.bar_chart(
            pd.DataFrame(
                {"mois": length["months"], "patients": length["n_persons"]}
            ).set_index("mois"),
            height=240,
        )

    cumulative = achilles.get("cumulative_observation", {})
    if cumulative.get("months_threshold"):
        st.markdown("**Observation cumulée (% de patients suivis au moins N mois)**")
        st.line_chart(
            pd.DataFrame(
                {"mois": cumulative["months_threshold"], "% patients": cumulative["pct_persons"]}
            ).set_index("mois"),
            height=240,
        )

    by_year = achilles.get("continuous_observation_by_year", {})
    if by_year.get("year"):
        st.markdown("**Patients observés par année**")
        st.line_chart(
            pd.DataFrame(
                {"année": by_year["year"], "patients": by_year["n_persons"]}
            ).set_index("année"),
            height=240,
        )

    for key, label in (
        ("age_by_gender", "Âge par genre (quantiles)"),
        ("duration_by_gender", "Durée d'observation par genre (quantiles)"),
    ):
        rows = achilles.get(key, {}).get("rows", [])
        if rows:
            st.markdown(f"**{label}**")
            ui.show_table(rows)
            ui.download_csv(f"Exporter — {label} (CSV)", rows, f"{key}.csv", key=f"dl_{key}")


def _render_clinical(results: dict) -> None:
    achilles = results.get("achilles_like", {})
    mapping = results.get("mapping", {})
    global_stats = achilles.get("global", {})
    terms = mapping.get("terms", {})
    rows_stats = mapping.get("rows", {})

    ui.metrics([
        ("Enregistrements", ui.fmt_int(global_stats.get("total_rows"))),
        ("Patients distincts", ui.fmt_int(global_stats.get("distinct_persons"))),
        ("Termes mappés", ui.fmt_pct(terms.get("pct_terms_mapped"))),
        ("Lignes mappées", ui.fmt_pct(rows_stats.get("pct_rows_mapped"))),
    ])

    by_month = achilles.get("by_month", {})
    if by_month.get("month_start"):
        st.markdown("**Volumétrie mensuelle**")
        st.line_chart(
            pd.DataFrame(
                {"mois": pd.to_datetime(by_month["month_start"]), "enregistrements": by_month["count"]}
            ).set_index("mois"),
            height=260,
        )

    per_person = achilles.get("records_per_person", {})
    if per_person.get("records_per_person"):
        st.markdown(
            f"**Enregistrements par patient** (regroupés au-delà de {per_person.get('max_bin')})"
        )
        st.bar_chart(
            pd.DataFrame(
                {
                    "enregistrements": per_person["records_per_person"],
                    "patients": per_person["n_persons"],
                }
            ).set_index("enregistrements"),
            height=240,
        )

    top_concepts = achilles.get("top_concepts", [])
    if top_concepts:
        st.markdown("**Concepts les plus fréquents**")
        ui.show_table(top_concepts)
        ui.download_csv("Exporter les concepts (CSV)", top_concepts, "top_concepts.csv",
                        key="dl_top_concepts")

    if not mapping:
        # Domains without a source_value column (e.g. Note) carry no mapping
        # block — the engine skips those statistics rather than failing.
        st.caption("Ce domaine n'expose pas de valeur source : pas de statistiques de mapping.")
        return

    unmapped = mapping.get("top_unmapped_terms", [])
    st.markdown("**Termes source non mappés**")
    if unmapped:
        ui.show_table(unmapped)
        ui.download_csv("Exporter les non-mappés (CSV)", unmapped, "top_unmapped.csv",
                        key="dl_unmapped")
    else:
        st.success("Aucun terme non mappé dans cette table.")

    with st.expander("Détail des statistiques de mapping"):
        ui.show_table([
            {"niveau": "Termes", **terms},
            {"niveau": "Lignes", **rows_stats},
        ])


def render_results(domain: str, results: dict) -> None:
    """Dispatch a snapshot's results to the right renderer."""
    if domain == "Dashboard":
        _render_dashboard(results)
    elif domain == "Person":
        _render_person(results)
    elif domain == "ObservationPeriod":
        _render_observation_period(results)
    elif domain == "Conformity":
        _render_conformity(results)
    else:
        _render_clinical(results)


def _render_conformity(report: dict) -> None:
    score = report.get("score")
    ui.metrics([
        ("Score de conformité", f"{score}/100" if score is not None else "—"),
        ("Contrôles", report.get("total_checks", 0)),
        ("Réussis", report.get("passed", 0)),
        ("Avertissements", report.get("warnings", 0)),
        ("Échecs", report.get("failures", 0)),
    ])
    checks = report.get("checks", [])
    if not checks:
        st.caption("Aucun contrôle exécuté.")
        return
    statuses = sorted({c.get("status", "") for c in checks})
    chosen = st.multiselect("Filtrer par statut", statuses, default=statuses, key="conf_status")
    filtered = [c for c in checks if c.get("status") in chosen]
    ui.show_table(filtered, columns=["status", "category", "id", "description", "detail", "value"])
    ui.download_csv("Exporter les contrôles (CSV)", checks, "conformity_checks.csv",
                    key="dl_conformity")


# ── CSV exports mirroring the server's /api/quality/export ───────────────

_EXPORT_TABLES = {
    "top_concepts": "Concepts fréquents",
    "top_unmapped": "Termes non mappés",
    "domain_stats": "Statistiques par domaine",
    "age_by_gender": "Âge par genre",
    "duration_by_gender": "Durée par genre",
}


def snapshot_csv(snapshot: dict, table_type: str) -> tuple[str, str]:
    """Build (filename, csv_text) for a snapshot table — same shapes as the API."""
    results = snapshot["results"]
    output = io.StringIO()
    writer = csv.writer(output)
    safe_cdm = re.sub(r"[^\w\-.]", "_", snapshot["cdm_name"])
    safe_domain = re.sub(r"[^\w\-.]", "_", snapshot["domain"])
    filename = f"{safe_cdm}_{safe_domain}_v{snapshot['version']}_{table_type}.csv"

    if table_type == "top_concepts":
        writer.writerow(["concept_id", "concept_name", "source_value", "n_records", "n_persons"])
        for row in results.get("achilles_like", {}).get("top_concepts", []):
            writer.writerow([
                row.get("concept_id"), csv_safe(row.get("concept_name")),
                csv_safe(row.get("source_value")), row.get("n_records"), row.get("n_persons"),
            ])
    elif table_type == "top_unmapped":
        unmapped = results.get("mapping", {}).get("top_unmapped_terms", [])
        has_name = any("source_name" in u for u in unmapped)
        header = ["source_value"] + (["source_name"] if has_name else []) + ["count"]
        writer.writerow(header)
        for row in unmapped:
            line = [csv_safe(row.get("source_value"))]
            if has_name:
                line.append(csv_safe(row.get("source_name", "")))
            line.append(row.get("count"))
            writer.writerow(line)
    elif table_type == "domain_stats":
        writer.writerow([
            "domain", "total_records", "distinct_persons", "pct_persons",
            "total_terms", "mapped_terms", "unmapped_terms", "pct_terms_mapped",
        ])
        for row in results.get("summary", {}).get("domains", []):
            writer.writerow([
                csv_safe(row.get("domain")), row.get("total_records"), row.get("distinct_persons"),
                row.get("pct_persons"), row.get("total_terms"), row.get("mapped_terms"),
                row.get("unmapped_terms"), row.get("pct_terms_mapped"),
            ])
    elif table_type in ("age_by_gender", "duration_by_gender"):
        rows = results.get("achilles_like", {}).get(table_type, {}).get("rows", [])
        if table_type == "age_by_gender":
            writer.writerow(["gender_name", "n", "mean_age", "p10", "p25", "median_age", "p75", "p90"])
            keys = ["gender_name", "n", "mean_age", "p10", "p25", "median_age", "p75", "p90"]
        else:
            writer.writerow(["gender_name", "n", "mean_months", "p10", "p25", "median_months", "p75", "p90"])
            keys = ["gender_name", "n", "mean_months", "p10", "p25", "median_months", "p75", "p90"]
        for row in rows:
            writer.writerow([csv_safe(row.get(k)) if k == "gender_name" else row.get(k) for k in keys])
    else:
        raise ValueError(f"Unknown table type: {table_type}")

    return filename, output.getvalue()


# ── tabs ─────────────────────────────────────────────────────────────────

def _tab_analyse(config, cdm, store) -> None:
    domains = _available_domains(cdm)
    left, right = st.columns([3, 1])
    with left:
        chosen = st.multiselect(
            "Domaines à analyser", domains,
            default=[d for d in ("Dashboard",) if d in domains],
            key="quality_domains",
        )
    with right:
        st.write("")
        st.write("")
        if st.button("Rafraîchir la liste", use_container_width=True):
            st.session_state.pop(f"_quality_domains_{cdm.name}", None)
            st.rerun()

    params = config.analysis
    with st.expander("Paramètres d'analyse (issus de config.toml)"):
        st.write(
            {
                "top_unmapped_terms": params.top_unmapped_terms,
                "top_concepts": params.top_concepts,
                "max_records_per_person": params.max_records_per_person,
                "max_observation_months": params.max_observation_months,
            }
        )

    if st.button("Lancer l'analyse", type="primary", disabled=not chosen):
        saved = _run_analyses(cdm, store, config, chosen)
        if saved:
            st.success(
                f"{len(saved)} snapshot(s) enregistré(s) : "
                + ", ".join(f"{s['domain']} v{s['version']}" for s in saved)
            )
            st.session_state["quality_last_domain"] = saved[-1]["domain"]

    st.divider()
    analysed = store.analyzed_domains(cdm.name)
    analysed = [d for d in analysed if d != "Conformity"]
    if not analysed:
        st.info("Aucun résultat pour l'instant — lancez une analyse ci-dessus.")
        return

    default_index = 0
    last = st.session_state.get("quality_last_domain")
    if last in analysed:
        default_index = analysed.index(last)
    domain = st.selectbox("Résultats du domaine", analysed, index=default_index, key="quality_view_domain")
    snapshot = store.latest_snapshot(cdm.name, domain)
    if not snapshot:
        return
    st.caption(f"Snapshot v{snapshot['version']} — {snapshot['created_at']}")
    render_results(domain, snapshot["results"])


def _tab_conformity(config, cdm, store) -> None:
    st.caption(
        "Contrôles structurels du CDM (clés, dates, concepts, cohérence des tables). "
        "Le résultat est versionné comme un snapshot du domaine « Conformity »."
    )
    if st.button("Lancer les contrôles de conformité", type="primary"):
        progress = st.progress(0.0, text="Préparation…")

        def _on_progress(step_name, completed, total):
            progress.progress(min(completed / max(total, 1), 1.0), text=f"Contrôle : {step_name}")

        try:
            with connection(cdm) as conn:
                report = run_conformity_checks(
                    conn, omop_schema=schema_map(cdm), on_progress=_on_progress
                )
            store.save_snapshot(cdm.name, "Conformity", report)
            st.success(f"Conformité terminée — score {report.get('score')}/100")
        except Exception as exc:  # noqa: BLE001
            ui.error_box(exc, "Contrôles de conformité en échec")
        finally:
            progress.empty()

    snapshot = store.latest_snapshot(cdm.name, "Conformity")
    if snapshot:
        st.caption(f"Dernier rapport : v{snapshot['version']} — {snapshot['created_at']}")
        _render_conformity(snapshot["results"])
    else:
        st.info("Aucun rapport de conformité pour ce CDM.")


def _tab_history(config, cdm, store) -> None:
    snapshots = store.list_snapshots(cdm.name)
    if not snapshots:
        st.info("Aucun snapshot enregistré.")
        return
    ui.show_table(snapshots, columns=["id", "domain", "version", "created_at"])

    labels = {
        f"#{s['id']} — {s['domain']} v{s['version']} ({s['created_at']})": s["id"]
        for s in snapshots
    }
    chosen = st.selectbox("Snapshot", list(labels), key="history_snapshot")
    snapshot = store.get_snapshot(labels[chosen])
    if not snapshot:
        return

    columns = st.columns(3)
    with columns[0]:
        ui.download_json(
            "Télécharger le JSON", snapshot["results"],
            f"{snapshot['cdm_name']}_{snapshot['domain']}_v{snapshot['version']}.json",
            key="dl_snapshot_json",
        )
    with columns[1]:
        available = [
            table
            for table in _EXPORT_TABLES
            if _has_export_table(snapshot["results"], table)
        ]
        if available:
            table_type = st.selectbox(
                "Table à exporter", available,
                format_func=lambda t: _EXPORT_TABLES[t], key="history_export",
            )
            filename, content = snapshot_csv(snapshot, table_type)
            st.download_button(
                "Télécharger le CSV", content.encode("utf-8"), file_name=filename,
                mime="text/csv", key="dl_snapshot_csv",
            )
    with columns[2]:
        st.write("")
        if st.button("Supprimer ce snapshot", key="delete_snapshot"):
            store.delete_snapshot(snapshot["id"])
            st.rerun()

    st.divider()
    render_results(snapshot["domain"], snapshot["results"])


def _has_export_table(results: dict, table_type: str) -> bool:
    achilles = results.get("achilles_like", {})
    if table_type == "top_concepts":
        return bool(achilles.get("top_concepts"))
    if table_type == "top_unmapped":
        return bool(results.get("mapping", {}).get("top_unmapped_terms"))
    if table_type == "domain_stats":
        return bool(results.get("summary", {}).get("domains"))
    return bool(achilles.get(table_type, {}).get("rows"))


def _tab_compare(config, cdm, store) -> None:
    st.caption(
        "Compare deux snapshots du même domaine (deux dates, ou deux bases si "
        "plusieurs sont configurées) et signale les écarts au-delà du seuil."
    )
    snapshots = store.list_snapshots()
    if len(snapshots) < 2:
        st.info("Il faut au moins deux snapshots pour comparer.")
        return

    domains = sorted({s["domain"] for s in snapshots if s["domain"] != "Conformity"})
    domain = st.selectbox("Domaine", domains, key="compare_domain")
    candidates = [s for s in snapshots if s["domain"] == domain]
    if len(candidates) < 2:
        st.info("Ce domaine n'a qu'un seul snapshot.")
        return

    labels = {
        f"{s['cdm_name']} — v{s['version']} ({s['created_at']})": s["id"] for s in candidates
    }
    keys = list(labels)
    left, right = st.columns(2)
    with left:
        label_a = st.selectbox("Référence (A)", keys, index=min(1, len(keys) - 1), key="compare_a")
    with right:
        label_b = st.selectbox("Comparé (B)", keys, index=0, key="compare_b")

    threshold = st.slider(
        "Seuil d'alerte (% d'écart)", 1.0, 50.0,
        float(config.analysis.comparison_alert_threshold), 0.5,
    )
    if labels[label_a] == labels[label_b]:
        st.warning("Sélectionnez deux snapshots différents.")
        return

    snap_a = store.get_snapshot(labels[label_a])
    snap_b = store.get_snapshot(labels[label_b])
    comparison = compare_snapshots(snap_a["results"], snap_b["results"], threshold=threshold)

    alerts = comparison.get("alerts", [])
    if alerts:
        st.warning(f"{len(alerts)} écart(s) au-delà de {threshold} %")
        ui.show_table(alerts)
    else:
        st.success(f"Aucun écart supérieur à {threshold} %.")

    diffs = comparison.get("diffs", {})
    if diffs:
        st.markdown("**Différences détaillées**")
        st.json(diffs, expanded=False)

    html = build_comparison_html_report(
        snap_a["cdm_name"], snap_b["cdm_name"],
        [
            {
                "domain": domain,
                "diffs": diffs,
                "alerts": alerts,
                "threshold": threshold,
                "snap_a": {"version": snap_a["version"], "created_at": snap_a["created_at"]},
                "snap_b": {"version": snap_b["version"], "created_at": snap_b["created_at"]},
                "results_a": snap_a["results"],
                "results_b": snap_b["results"],
            }
        ],
        lang=config.lang,
    )
    st.download_button(
        "Télécharger le rapport de comparaison (HTML)", html.encode("utf-8"),
        file_name=f"opal_comparison_{domain}.html", mime="text/html", key="dl_comparison",
    )


def _tab_report(config, cdm, store) -> None:
    domains = [d for d in store.analyzed_domains(cdm.name) if d != "Conformity"]
    if not domains:
        st.info("Analysez au moins un domaine pour générer un rapport.")
        return
    chosen = st.multiselect("Domaines inclus", domains, default=domains, key="report_domains")
    if not chosen:
        return

    snapshots_data = {}
    for domain in chosen:
        snapshot = store.latest_snapshot(cdm.name, domain)
        if snapshot:
            snapshots_data[domain] = {
                "version": snapshot["version"],
                "created_at": snapshot["created_at"],
                "results": snapshot["results"],
            }

    html = build_html_report(cdm.name, snapshots_data, lang=config.lang)
    st.download_button(
        "Télécharger le rapport (HTML)", html.encode("utf-8"),
        file_name=f"opal_quality_{cdm.name}.html", mime="text/html", type="primary",
        key="dl_report",
    )
    with st.expander("Aperçu du rapport"):
        st.components.v1.html(html, height=600, scrolling=True)


def render(config, cdm, store) -> None:
    ui.brick_header(TITLE, SUBTITLE, ICON)
    tabs = st.tabs(["Analyse", "Conformité", "Historique", "Comparaison", "Rapport"])
    with tabs[0]:
        _tab_analyse(config, cdm, store)
    with tabs[1]:
        _tab_conformity(config, cdm, store)
    with tabs[2]:
        _tab_history(config, cdm, store)
    with tabs[3]:
        _tab_compare(config, cdm, store)
    with tabs[4]:
        _tab_report(config, cdm, store)
