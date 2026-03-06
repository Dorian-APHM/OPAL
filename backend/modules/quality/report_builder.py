"""
HTML report builder — generates a self-contained quality report.
"""
from datetime import datetime
import html as html_mod


_LABELS = {
    "en": {
        "title": "OPAL Quality Report",
        "comparison_title": "OPAL Quality Comparison Report",
        "vs": "vs",
        "change": "Change",
        "alert": "Alert",
        "alerts": "Alerts",
        "no_alerts": "No alerts — all metrics within threshold",
        "threshold": "Alert Threshold",
        "severity": "Severity",
        "warning": "WARNING",
        "critical": "CRITICAL",
        "metrics_comparison": "Metrics Comparison",
        "side_by_side": "Side-by-Side Details",
        "generated": "Generated on",
        "cdm": "CDM",
        "version": "Version",
        "date": "Date",
        "summary": "Summary",
        "total_persons": "Total Persons",
        "total_records": "Total Records",
        "distinct_persons": "Distinct Persons",
        "pct_terms_mapped": "% Terms Mapped",
        "pct_rows_mapped": "% Rows Mapped",
        "top_concepts": "Top Concepts",
        "concept_id": "Concept ID",
        "concept_name": "Concept Name",
        "source_value": "Source Value",
        "n_records": "Records",
        "n_persons": "Persons",
        "mapping_quality": "Mapping Quality",
        "terms": "Terms",
        "rows": "Rows",
        "total": "Total",
        "mapped": "Mapped",
        "unmapped": "Unmapped",
        "pct_mapped": "% Mapped",
        "top_unmapped": "Top Unmapped Terms",
        "occurrences": "Occurrences",
        "gender_distribution": "Gender Distribution",
        "birth_year": "Birth Year Distribution",
        "domain_stats": "Statistics by Domain",
        "domain": "Domain",
        "no_data": "No data available",
        "monthly_evolution": "Monthly Evolution",
        "records_per_person": "Records per Person",
    },
    "fr": {
        "title": "Rapport Qualité OPAL",
        "comparison_title": "Rapport de Comparaison Qualité OPAL",
        "vs": "vs",
        "change": "Variation",
        "alert": "Alerte",
        "alerts": "Alertes",
        "no_alerts": "Aucune alerte — toutes les métriques dans le seuil",
        "threshold": "Seuil d'alerte",
        "severity": "Sévérité",
        "warning": "AVERTISSEMENT",
        "critical": "CRITIQUE",
        "metrics_comparison": "Comparaison des Métriques",
        "side_by_side": "Détails Côte à Côte",
        "generated": "Généré le",
        "cdm": "CDM",
        "version": "Version",
        "date": "Date",
        "summary": "Résumé",
        "total_persons": "Total Personnes",
        "total_records": "Total Lignes",
        "distinct_persons": "Personnes Distinctes",
        "pct_terms_mapped": "% Termes Mappés",
        "pct_rows_mapped": "% Lignes Mappées",
        "top_concepts": "Top Concepts",
        "concept_id": "Concept ID",
        "concept_name": "Nom du Concept",
        "source_value": "Code Source",
        "n_records": "Nb Records",
        "n_persons": "Nb Personnes",
        "mapping_quality": "Qualité du Mapping",
        "terms": "Termes",
        "rows": "Lignes",
        "total": "Total",
        "mapped": "Mappés",
        "unmapped": "Non Mappés",
        "pct_mapped": "% Mappé",
        "top_unmapped": "Top Termes Non Mappés",
        "occurrences": "Occurrences",
        "gender_distribution": "Répartition par Genre",
        "birth_year": "Répartition Année de Naissance",
        "domain_stats": "Statistiques par Domaine",
        "domain": "Domaine",
        "no_data": "Aucune donnée disponible",
        "monthly_evolution": "Évolution Mensuelle",
        "records_per_person": "Records par Personne",
    },
}


def _esc(val) -> str:
    if val is None:
        return ""
    return html_mod.escape(str(val))


def build_html_report(cdm_name: str, snapshots_data: dict, lang: str = "en") -> str:
    """
    Build a self-contained HTML report from latest snapshots.

    Args:
        cdm_name: CDM name.
        snapshots_data: Dict mapping domain -> {version, created_at, results}.
        lang: Language for labels ('en' or 'fr').
    """
    L = _LABELS.get(lang, _LABELS["en"])
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    sections = []

    # Dashboard section
    if "Dashboard" in snapshots_data:
        sections.append(_render_dashboard(snapshots_data["Dashboard"], L))

    # Person section
    if "Person" in snapshots_data:
        sections.append(_render_person(snapshots_data["Person"], L))

    # Clinical domains
    for dom in ["Condition", "Drug", "Measurement", "Observation", "Procedure",
                "Visit", "Device", "Death"]:
        if dom in snapshots_data:
            sections.append(_render_clinical(dom, snapshots_data[dom], L))

    body = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(L['title'])} — {_esc(cdm_name)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         color: #333; background: #f8f9fa; padding: 24px; line-height: 1.5; }}
  .container {{ max-width: 1100px; margin: 0 auto; }}
  h1 {{ color: #1f77b4; margin-bottom: 4px; font-size: 28px; }}
  h2 {{ color: #2c3e50; margin: 32px 0 16px; font-size: 22px; border-bottom: 2px solid #1f77b4; padding-bottom: 6px; }}
  h3 {{ color: #34495e; margin: 20px 0 10px; font-size: 17px; }}
  .meta {{ color: #666; font-size: 13px; margin-bottom: 24px; }}
  .kpi-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }}
  .kpi {{ background: #fff; border-radius: 8px; padding: 16px 20px; flex: 1; min-width: 160px;
          box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }}
  .kpi-value {{ font-size: 28px; font-weight: 700; color: #1f77b4; }}
  .kpi-label {{ font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px;
           overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px; }}
  th {{ background: #1f77b4; color: #fff; font-weight: 600; text-align: left;
       padding: 10px 12px; font-size: 13px; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #eee; font-size: 13px; }}
  tr:nth-child(even) td {{ background: #f9fafb; }}
  tr:hover td {{ background: #e8f4fd; }}
  .pct-bar {{ display: inline-block; height: 8px; border-radius: 4px; background: #1f77b4; }}
  .pct-bar-bg {{ display: inline-block; width: 80px; height: 8px; border-radius: 4px; background: #e9ecef; margin-right: 6px; }}
  .mapping-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }}
  .badge-good {{ background: #d4edda; color: #155724; }}
  .badge-warn {{ background: #fff3cd; color: #856404; }}
  .badge-bad {{ background: #f8d7da; color: #721c24; }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .kpi {{ box-shadow: none; border: 1px solid #ddd; }}
    table {{ box-shadow: none; border: 1px solid #ddd; }}
  }}
  @media (max-width: 600px) {{
    .kpi-row {{ flex-direction: column; }}
    .mapping-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="container">
  <h1>{_esc(L['title'])}</h1>
  <p class="meta">{_esc(L['cdm'])}: <strong>{_esc(cdm_name)}</strong> &mdash; {_esc(L['generated'])} {now}</p>
  {body}
</div>
</body>
</html>"""


def _render_dashboard(data: dict, L: dict) -> str:
    r = data["results"]
    summary = r.get("summary", {})
    total_persons = summary.get("total_persons", 0)
    domains = summary.get("domains", [])

    kpis = f"""
    <h2>Dashboard</h2>
    <p class="meta">{L['version']} {data['version']} &mdash; {data.get('created_at', '')}</p>
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-value">{total_persons:,}</div><div class="kpi-label">{L['total_persons']}</div></div>
    </div>
    """

    if domains:
        rows = ""
        for d in domains:
            pct = d.get("pct_terms_mapped")
            badge_cls = "badge-good" if pct and pct >= 80 else ("badge-warn" if pct and pct >= 50 else "badge-bad")
            pct_str = f"{pct:.1f}%" if pct is not None else "N/A"
            rows += f"""<tr>
              <td><strong>{_esc(d['domain'])}</strong></td>
              <td>{d.get('total_records', 0):,}</td>
              <td>{d.get('distinct_persons', 0):,}</td>
              <td>{d.get('total_terms', 0):,}</td>
              <td>{d.get('mapped_terms', 0):,}</td>
              <td>{d.get('unmapped_terms', 0):,}</td>
              <td><span class="badge {badge_cls}">{pct_str}</span></td>
            </tr>"""

        kpis += f"""
        <h3>{L['domain_stats']}</h3>
        <table>
          <tr><th>{L['domain']}</th><th>{L['total_records']}</th><th>{L['distinct_persons']}</th>
              <th>{L['total']}</th><th>{L['mapped']}</th><th>{L['unmapped']}</th><th>{L['pct_mapped']}</th></tr>
          {rows}
        </table>
        """

    return kpis


def _render_person(data: dict, L: dict) -> str:
    r = data["results"]
    ps = r.get("achilles_like", {}).get("person_summary", {})
    total = ps.get("total_persons", 0)

    html = f"""
    <h2>Person</h2>
    <p class="meta">{L['version']} {data['version']} &mdash; {data.get('created_at', '')}</p>
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-value">{total:,}</div><div class="kpi-label">{L['total_persons']}</div></div>
    </div>
    """

    # Gender distribution table
    gd = ps.get("gender_distribution", {})
    names = gd.get("gender_name", [])
    counts = gd.get("count", [])
    if names:
        rows = ""
        for name, count in zip(names, counts):
            pct = round(count / total * 100, 1) if total > 0 else 0
            rows += f"<tr><td>{_esc(name)}</td><td>{count:,}</td><td>{pct}%</td></tr>"
        html += f"""
        <h3>{L['gender_distribution']}</h3>
        <table><tr><th>Gender</th><th>Count</th><th>%</th></tr>{rows}</table>
        """

    return html


def _render_clinical(domain: str, data: dict, L: dict) -> str:
    r = data["results"]
    g = r.get("achilles_like", {}).get("global", {})
    total_rows = g.get("total_rows", 0)
    distinct_persons = g.get("distinct_persons", 0)

    html = f"""
    <h2>{_esc(domain)}</h2>
    <p class="meta">{L['version']} {data['version']} &mdash; {data.get('created_at', '')}</p>
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-value">{total_rows:,}</div><div class="kpi-label">{L['total_records']}</div></div>
      <div class="kpi"><div class="kpi-value">{distinct_persons:,}</div><div class="kpi-label">{L['distinct_persons']}</div></div>
    </div>
    """

    # Mapping quality
    mapping = r.get("mapping", {})
    terms = mapping.get("terms", {})
    rows = mapping.get("rows", {})

    if terms:
        pct_t = terms.get("pct_terms_mapped")
        pct_r = rows.get("pct_rows_mapped")
        badge_t = "badge-good" if pct_t and pct_t >= 80 else ("badge-warn" if pct_t and pct_t >= 50 else "badge-bad")
        badge_r = "badge-good" if pct_r and pct_r >= 80 else ("badge-warn" if pct_r and pct_r >= 50 else "badge-bad")

        html += f"""
        <h3>{L['mapping_quality']}</h3>
        <div class="mapping-grid">
          <table>
            <tr><th colspan="2">{L['terms']}</th></tr>
            <tr><td>{L['total']}</td><td>{terms.get('total_terms', 0):,}</td></tr>
            <tr><td>{L['mapped']}</td><td>{terms.get('mapped_terms', 0):,}</td></tr>
            <tr><td>{L['unmapped']}</td><td>{terms.get('unmapped_terms', 0):,}</td></tr>
            <tr><td>{L['pct_mapped']}</td><td><span class="badge {badge_t}">{f'{pct_t:.1f}%' if pct_t is not None else 'N/A'}</span></td></tr>
          </table>
          <table>
            <tr><th colspan="2">{L['rows']}</th></tr>
            <tr><td>{L['total']}</td><td>{rows.get('total_rows', 0):,}</td></tr>
            <tr><td>{L['mapped']}</td><td>{rows.get('mapped_rows', 0):,}</td></tr>
            <tr><td>{L['unmapped']}</td><td>{rows.get('unmapped_rows', 0):,}</td></tr>
            <tr><td>{L['pct_mapped']}</td><td><span class="badge {badge_r}">{f'{pct_r:.1f}%' if pct_r is not None else 'N/A'}</span></td></tr>
          </table>
        </div>
        """

    # Top concepts
    concepts = r.get("achilles_like", {}).get("top_concepts", [])
    if concepts:
        rows_html = ""
        for c in concepts[:20]:
            rows_html += f"""<tr>
              <td>{_esc(c.get('concept_id', ''))}</td>
              <td>{_esc(c.get('concept_name', ''))}</td>
              <td>{_esc(c.get('source_value', ''))}</td>
              <td>{c.get('n_records', 0):,}</td>
              <td>{c.get('n_persons', 0):,}</td>
            </tr>"""
        html += f"""
        <h3>{L['top_concepts']}</h3>
        <table>
          <tr><th>{L['concept_id']}</th><th>{L['concept_name']}</th><th>{L['source_value']}</th>
              <th>{L['n_records']}</th><th>{L['n_persons']}</th></tr>
          {rows_html}
        </table>
        """

    # Top unmapped
    unmapped = mapping.get("top_unmapped_terms", [])
    if unmapped:
        rows_html = ""
        for u in unmapped[:20]:
            rows_html += f"""<tr>
              <td>{_esc(u.get('source_value', ''))}</td>
              <td>{u.get('count', 0):,}</td>
            </tr>"""
        html += f"""
        <h3>{L['top_unmapped']}</h3>
        <table>
          <tr><th>{L['source_value']}</th><th>{L['occurrences']}</th></tr>
          {rows_html}
        </table>
        """

    return html


# ============================================================
# Comparison HTML report
# ============================================================

def build_comparison_html_report(
    cdm_name_a: str, cdm_name_b: str,
    comparisons: list[dict],
    lang: str = "en",
) -> str:
    """
    Build a self-contained HTML comparison report.

    Args:
        cdm_name_a: First CDM name (reference).
        cdm_name_b: Second CDM name (target).
        comparisons: List of dicts with keys:
            domain, diffs, alerts, threshold, snap_a, snap_b, results_a, results_b
        lang: Language for labels.
    """
    L = _LABELS.get(lang, _LABELS["en"])
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    sections = []
    for comp in comparisons:
        sections.append(_render_comparison_domain(comp, cdm_name_a, cdm_name_b, L))

    body = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(L['comparison_title'])} — {_esc(cdm_name_a)} {L['vs']} {_esc(cdm_name_b)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         color: #333; background: #f8f9fa; padding: 24px; line-height: 1.5; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  h1 {{ color: #1f77b4; margin-bottom: 4px; font-size: 28px; }}
  h2 {{ color: #2c3e50; margin: 32px 0 16px; font-size: 22px; border-bottom: 2px solid #1f77b4; padding-bottom: 6px; }}
  h3 {{ color: #34495e; margin: 20px 0 10px; font-size: 17px; }}
  h4 {{ color: #555; margin: 10px 0 6px; font-size: 14px; }}
  .meta {{ color: #666; font-size: 13px; margin-bottom: 24px; }}
  .kpi-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }}
  .kpi {{ background: #fff; border-radius: 8px; padding: 16px 20px; flex: 1; min-width: 160px;
          box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }}
  .kpi-value {{ font-size: 28px; font-weight: 700; color: #1f77b4; }}
  .kpi-label {{ font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px;
           overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px; }}
  th {{ background: #1f77b4; color: #fff; font-weight: 600; text-align: left;
       padding: 10px 12px; font-size: 13px; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #eee; font-size: 13px; }}
  tr:nth-child(even) td {{ background: #f9fafb; }}
  tr:hover td {{ background: #e8f4fd; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }}
  .badge-good {{ background: #d4edda; color: #155724; }}
  .badge-warn {{ background: #fff3cd; color: #856404; }}
  .badge-bad {{ background: #f8d7da; color: #721c24; }}
  .badge-neutral {{ background: #e2e3e5; color: #383d41; }}
  .side-by-side {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
  .side-by-side > div {{ min-width: 0; }}
  .mapping-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
  .alert-box {{ background: #fff3cd; border: 1px solid #ffc107; border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; }}
  .alert-box.critical {{ background: #f8d7da; border-color: #f5c6cb; }}
  .no-alert {{ background: #d4edda; border: 1px solid #c3e6cb; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; color: #155724; }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .kpi, table {{ box-shadow: none; border: 1px solid #ddd; }}
  }}
  @media (max-width: 800px) {{
    .side-by-side, .mapping-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="container">
  <h1>{_esc(L['comparison_title'])}</h1>
  <p class="meta">{_esc(cdm_name_a)} {L['vs']} {_esc(cdm_name_b)} &mdash; {_esc(L['generated'])} {now}</p>
  {body}
</div>
</body>
</html>"""


def _svg_bar_chart_overlay(data_a: list[tuple], data_b: list[tuple],
                           label_a: str, label_b: str,
                           width: int = 550, height: int = 200,
                           color_a: str = "#1f77b4", color_b: str = "#2bc459") -> str:
    """Generate an inline SVG bar chart overlaying two series."""
    if not data_a and not data_b:
        return ""
    all_vals = [v for _, v in data_a] + [v for _, v in data_b]
    max_val = max(all_vals) if all_vals else 1
    if max_val == 0:
        max_val = 1

    margin_left, margin_bottom = 60, 40
    chart_w = width - margin_left - 10
    chart_h = height - margin_bottom - 10

    # Merge labels in order
    labels_a = [l for l, _ in data_a]
    labels_b = [l for l, _ in data_b]
    all_labels = list(dict.fromkeys(labels_a + labels_b))
    n = len(all_labels)
    if n == 0:
        return ""

    dict_a = dict(data_a)
    dict_b = dict(data_b)
    bar_w = max(2, chart_w / n / 2.5)

    svg = f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" style="background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-bottom:16px">\n'
    # Axes
    svg += f'<line x1="{margin_left}" y1="5" x2="{margin_left}" y2="{height - margin_bottom}" stroke="#ccc"/>\n'
    svg += f'<line x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - 10}" y2="{height - margin_bottom}" stroke="#ccc"/>\n'

    # Y-axis ticks
    for i in range(5):
        y = 5 + (chart_h * (4 - i) / 4)
        val = int(max_val * i / 4)
        svg += f'<text x="{margin_left - 5}" y="{y + 4}" text-anchor="end" font-size="9" fill="#888">{val:,}</text>\n'
        svg += f'<line x1="{margin_left}" y1="{y}" x2="{width - 10}" y2="{y}" stroke="#eee"/>\n'

    # Bars
    for idx, label in enumerate(all_labels):
        x_center = margin_left + (idx + 0.5) * chart_w / n
        va = dict_a.get(label, 0)
        vb = dict_b.get(label, 0)
        ha = (va / max_val) * chart_h
        hb = (vb / max_val) * chart_h
        svg += f'<rect x="{x_center - bar_w}" y="{height - margin_bottom - ha}" width="{bar_w}" height="{ha}" fill="{color_a}" opacity="0.7"/>\n'
        svg += f'<rect x="{x_center}" y="{height - margin_bottom - hb}" width="{bar_w}" height="{hb}" fill="{color_b}" opacity="0.7"/>\n'
        if n <= 20:
            svg += f'<text x="{x_center}" y="{height - margin_bottom + 12}" text-anchor="middle" font-size="8" fill="#888">{_esc(str(label)[:10])}</text>\n'

    # Legend
    svg += f'<rect x="{margin_left + 10}" y="8" width="10" height="10" fill="{color_a}" opacity="0.7"/>'
    svg += f'<text x="{margin_left + 24}" y="17" font-size="9" fill="#555">{_esc(label_a[:30])}</text>\n'
    svg += f'<rect x="{margin_left + 200}" y="8" width="10" height="10" fill="{color_b}" opacity="0.7"/>'
    svg += f'<text x="{margin_left + 214}" y="17" font-size="9" fill="#555">{_esc(label_b[:30])}</text>\n'

    svg += '</svg>\n'
    return svg


def _svg_donut_pair(data_a: list[tuple], data_b: list[tuple],
                    label_a: str, label_b: str,
                    colors: list[str] | None = None) -> str:
    """Generate two side-by-side SVG donut charts."""
    if not data_a and not data_b:
        return ""
    import math
    if colors is None:
        colors = ["#3498db", "#e74c3c", "#95a5a6", "#f39c12", "#9b59b6", "#1abc9c"]

    def _donut(data: list[tuple], cx: int, cy: int, r_outer: int, r_inner: int, label: str) -> str:
        total = sum(v for _, v in data) or 1
        s = ""
        angle = 0
        for i, (name, val) in enumerate(data):
            pct = val / total
            a_start = angle
            a_end = angle + pct * 2 * math.pi
            if pct < 0.001:
                angle = a_end
                continue
            large = 1 if pct > 0.5 else 0
            x1 = cx + r_outer * math.cos(a_start)
            y1 = cy + r_outer * math.sin(a_start)
            x2 = cx + r_outer * math.cos(a_end - 0.001)
            y2 = cy + r_outer * math.sin(a_end - 0.001)
            x3 = cx + r_inner * math.cos(a_end - 0.001)
            y3 = cy + r_inner * math.sin(a_end - 0.001)
            x4 = cx + r_inner * math.cos(a_start)
            y4 = cy + r_inner * math.sin(a_start)
            c = colors[i % len(colors)]
            s += f'<path d="M{x1:.1f},{y1:.1f} A{r_outer},{r_outer} 0 {large} 1 {x2:.1f},{y2:.1f} L{x3:.1f},{y3:.1f} A{r_inner},{r_inner} 0 {large} 0 {x4:.1f},{y4:.1f} Z" fill="{c}"/>\n'
            # Label on arc midpoint
            mid = (a_start + a_end) / 2
            lx = cx + (r_outer + 14) * math.cos(mid)
            ly = cy + (r_outer + 14) * math.sin(mid)
            if pct >= 0.05:
                s += f'<text x="{lx:.0f}" y="{ly:.0f}" text-anchor="middle" font-size="8" fill="#555">{_esc(name)} {pct*100:.0f}%</text>\n'
            angle = a_end
        s += f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" font-size="9" font-weight="600" fill="#333">{total:,}</text>\n'
        s += f'<text x="{cx}" y="{cy + 74}" text-anchor="middle" font-size="10" fill="#555">{_esc(label[:25])}</text>\n'
        return s

    svg = '<svg width="550" height="180" xmlns="http://www.w3.org/2000/svg" style="background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-bottom:16px">\n'
    svg += _donut(data_a, 140, 75, 55, 30, label_a)
    svg += _donut(data_b, 410, 75, 55, 30, label_b)
    svg += '</svg>\n'
    return svg


def _fmt(val, suffix="") -> str:
    """Format a value for display."""
    if val is None:
        return "N/A"
    if isinstance(val, float):
        return f"{val:,.1f}{suffix}"
    if isinstance(val, int):
        return f"{val:,}{suffix}"
    return str(val)


def _change_badge(pct, threshold) -> str:
    if pct is None:
        return '<span class="badge badge-neutral">-</span>'
    sign = "+" if pct > 0 else ""
    if abs(pct) > threshold * 2:
        cls = "badge-bad"
    elif abs(pct) > threshold:
        cls = "badge-warn"
    else:
        cls = "badge-good"
    return f'<span class="badge {cls}">{sign}{pct:.1f}%</span>'


def _render_comparison_domain(comp: dict, cdm_a: str, cdm_b: str, L: dict) -> str:
    domain = comp["domain"]
    diffs = comp["diffs"]
    alerts = comp["alerts"]
    threshold = comp["threshold"]
    snap_a = comp["snap_a"]
    snap_b = comp["snap_b"]
    results_a = comp["results_a"]
    results_b = comp["results_b"]

    label_a = f"{cdm_a} (v{snap_a['version']})"
    label_b = f"{cdm_b} (v{snap_b['version']})"

    html = f'<h2>{_esc(domain)}</h2>\n'
    html += f'<p class="meta">{_esc(label_a)} {L["vs"]} {_esc(label_b)} &mdash; {L["threshold"]}: {threshold}%</p>\n'

    # --- Diffs table ---
    if diffs:
        html += f'<h3>{_esc(L["metrics_comparison"])}</h3>\n'
        html += f'<table><tr><th>Metric</th><th>{_esc(label_a)}</th><th>{_esc(label_b)}</th><th>{_esc(L["change"])}</th></tr>\n'
        for metric, diff in diffs.items():
            val_a = diff["a"]
            val_b = diff["b"]
            pct = diff["pct_change"]
            html += f'<tr><td><strong>{_esc(metric)}</strong></td>'
            html += f'<td>{_fmt(val_a)}</td><td>{_fmt(val_b)}</td>'
            html += f'<td>{_change_badge(pct, threshold)}</td></tr>\n'
        html += '</table>\n'

    # --- Alerts ---
    if alerts:
        html += f'<h3>{_esc(L["alerts"])} ({len(alerts)})</h3>\n'
        for a in alerts:
            sev = a["severity"]
            cls = "critical" if sev == "critical" else ""
            sev_label = L.get(sev, sev.upper())
            sign = "+" if a["pct_change"] > 0 else ""
            html += f'<div class="alert-box {cls}"><strong>{_esc(a["metric"])}</strong>: '
            html += f'{_fmt(a["value_a"])} &rarr; {_fmt(a["value_b"])} '
            html += f'({sign}{a["pct_change"]:.1f}%) — <strong>{sev_label}</strong></div>\n'
    else:
        html += f'<div class="no-alert">{_esc(L["no_alerts"])}</div>\n'

    # --- Side-by-side domain-specific content ---
    if domain == "Dashboard":
        html += _render_comparison_dashboard(results_a, results_b, label_a, label_b, L)
    elif domain == "Person":
        html += _render_comparison_person(results_a, results_b, label_a, label_b, L)
    elif domain not in ("ObservationPeriod",):
        html += _render_comparison_clinical(results_a, results_b, label_a, label_b, L)

    return html


def _render_comparison_dashboard(ra: dict, rb: dict, label_a: str, label_b: str, L: dict) -> str:
    domains_a = {d["domain"]: d for d in ra.get("summary", {}).get("domains", [])}
    domains_b = {d["domain"]: d for d in rb.get("summary", {}).get("domains", [])}
    all_doms = sorted(set(domains_a) | set(domains_b))
    if not all_doms:
        return ""

    html = f'<h3>{_esc(L["domain_stats"])}</h3>\n'
    html += f'<table><tr><th>{L["domain"]}</th>'
    html += f'<th>{L["total_records"]} ({_esc(label_a)})</th><th>{L["total_records"]} ({_esc(label_b)})</th>'
    html += f'<th>{L["pct_mapped"]} ({_esc(label_a)})</th><th>{L["pct_mapped"]} ({_esc(label_b)})</th></tr>\n'
    for d in all_doms:
        da = domains_a.get(d, {})
        db = domains_b.get(d, {})
        pct_a = da.get("pct_terms_mapped")
        pct_b = db.get("pct_terms_mapped")
        badge_a_cls = "badge-good" if pct_a and pct_a >= 80 else ("badge-warn" if pct_a and pct_a >= 50 else "badge-bad")
        badge_b_cls = "badge-good" if pct_b and pct_b >= 80 else ("badge-warn" if pct_b and pct_b >= 50 else "badge-bad")
        html += f'<tr><td><strong>{_esc(d)}</strong></td>'
        html += f'<td>{_fmt(da.get("total_records"))}</td><td>{_fmt(db.get("total_records"))}</td>'
        html += f'<td><span class="badge {badge_a_cls}">{_fmt(pct_a, "%")}</span></td>'
        html += f'<td><span class="badge {badge_b_cls}">{_fmt(pct_b, "%")}</span></td></tr>\n'
    html += '</table>\n'
    return html


def _render_comparison_person(ra: dict, rb: dict, label_a: str, label_b: str, L: dict) -> str:
    ps_a = ra.get("achilles_like", {}).get("person_summary", {})
    ps_b = rb.get("achilles_like", {}).get("person_summary", {})

    html = '<div class="kpi-row">\n'
    html += f'<div class="kpi"><div class="kpi-value">{_fmt(ps_a.get("total_persons"))}</div>'
    html += f'<div class="kpi-label">{_esc(label_a)}</div></div>\n'
    html += f'<div class="kpi"><div class="kpi-value">{_fmt(ps_b.get("total_persons"))}</div>'
    html += f'<div class="kpi-label">{_esc(label_b)}</div></div>\n'
    html += '</div>\n'

    # Gender donut chart + table
    gd_a = ps_a.get("gender_distribution", {})
    gd_b = ps_b.get("gender_distribution", {})
    if gd_a.get("gender_name") or gd_b.get("gender_name"):
        html += f'<h3>{_esc(L["gender_distribution"])}</h3>\n'
        donut_a = list(zip(gd_a.get("gender_name", []), gd_a.get("count", [])))
        donut_b = list(zip(gd_b.get("gender_name", []), gd_b.get("count", [])))
        html += _svg_donut_pair(donut_a, donut_b, label_a, label_b)
        html += '<div class="side-by-side">\n'
        for label, gd, total in [(label_a, gd_a, ps_a.get("total_persons", 0)),
                                  (label_b, gd_b, ps_b.get("total_persons", 0))]:
            html += f'<div><h4 style="margin-bottom:8px">{_esc(label)}</h4><table><tr><th>Gender</th><th>Count</th><th>%</th></tr>\n'
            for name, cnt in zip(gd.get("gender_name", []), gd.get("count", [])):
                pct = round(cnt / total * 100, 1) if total > 0 else 0
                html += f'<tr><td>{_esc(name)}</td><td>{cnt:,}</td><td>{pct}%</td></tr>\n'
            html += '</table></div>\n'
        html += '</div>\n'

    return html


def _render_comparison_clinical(ra: dict, rb: dict, label_a: str, label_b: str, L: dict) -> str:
    ga = ra.get("achilles_like", {}).get("global", {})
    gb = rb.get("achilles_like", {}).get("global", {})
    ma = ra.get("mapping", {})
    mb = rb.get("mapping", {})

    # KPIs side-by-side
    html = '<div class="kpi-row">\n'
    html += f'<div class="kpi"><div class="kpi-value">{_fmt(ga.get("total_rows"))}</div><div class="kpi-label">{L["total_records"]} — {_esc(label_a)}</div></div>\n'
    html += f'<div class="kpi"><div class="kpi-value">{_fmt(gb.get("total_rows"))}</div><div class="kpi-label">{L["total_records"]} — {_esc(label_b)}</div></div>\n'
    html += f'<div class="kpi"><div class="kpi-value">{_fmt(ga.get("distinct_persons"))}</div><div class="kpi-label">{L["distinct_persons"]} — {_esc(label_a)}</div></div>\n'
    html += f'<div class="kpi"><div class="kpi-value">{_fmt(gb.get("distinct_persons"))}</div><div class="kpi-label">{L["distinct_persons"]} — {_esc(label_b)}</div></div>\n'
    html += '</div>\n'

    # Mapping quality side-by-side
    terms_a = ma.get("terms", {})
    terms_b = mb.get("terms", {})
    rows_a = ma.get("rows", {})
    rows_b = mb.get("rows", {})
    if terms_a or terms_b:
        html += f'<h3>{_esc(L["mapping_quality"])}</h3>\n'
        html += '<div class="side-by-side">\n'
        for label, terms, mrows in [(label_a, terms_a, rows_a), (label_b, terms_b, rows_b)]:
            pct_t = terms.get("pct_terms_mapped")
            pct_r = mrows.get("pct_rows_mapped")
            badge_t = "badge-good" if pct_t and pct_t >= 80 else ("badge-warn" if pct_t and pct_t >= 50 else "badge-bad")
            badge_r = "badge-good" if pct_r and pct_r >= 80 else ("badge-warn" if pct_r and pct_r >= 50 else "badge-bad")
            html += f'<div><h4 style="margin-bottom:8px">{_esc(label)}</h4>\n'
            html += '<div class="mapping-grid">\n'
            html += f'<table><tr><th colspan="2">{L["terms"]}</th></tr>'
            html += f'<tr><td>{L["total"]}</td><td>{_fmt(terms.get("total_terms"))}</td></tr>'
            html += f'<tr><td>{L["mapped"]}</td><td>{_fmt(terms.get("mapped_terms"))}</td></tr>'
            html += f'<tr><td>{L["unmapped"]}</td><td>{_fmt(terms.get("unmapped_terms"))}</td></tr>'
            html += f'<tr><td>{L["pct_mapped"]}</td><td><span class="badge {badge_t}">{_fmt(pct_t, "%")}</span></td></tr></table>\n'
            html += f'<table><tr><th colspan="2">{L["rows"]}</th></tr>'
            html += f'<tr><td>{L["total"]}</td><td>{_fmt(mrows.get("total_rows"))}</td></tr>'
            html += f'<tr><td>{L["mapped"]}</td><td>{_fmt(mrows.get("mapped_rows"))}</td></tr>'
            html += f'<tr><td>{L["unmapped"]}</td><td>{_fmt(mrows.get("unmapped_rows"))}</td></tr>'
            html += f'<tr><td>{L["pct_mapped"]}</td><td><span class="badge {badge_r}">{_fmt(pct_r, "%")}</span></td></tr></table>\n'
            html += '</div></div>\n'
        html += '</div>\n'

    # Monthly evolution overlay chart
    by_month_a = ra.get("achilles_like", {}).get("by_month", {})
    by_month_b = rb.get("achilles_like", {}).get("by_month", {})
    months_a = list(zip(by_month_a.get("month_start", []), by_month_a.get("count", [])))
    months_b = list(zip(by_month_b.get("month_start", []), by_month_b.get("count", [])))
    if months_a or months_b:
        # Sample every Nth point to keep chart readable
        step = max(1, max(len(months_a), len(months_b)) // 30)
        sampled_a = [(m[:7], c) for m, c in months_a[::step]]
        sampled_b = [(m[:7], c) for m, c in months_b[::step]]
        html += f'<h3>{_esc(L["monthly_evolution"])}</h3>\n'
        html += _svg_bar_chart_overlay(sampled_a, sampled_b, label_a, label_b, width=1100, height=220)

    # Records per person overlay chart
    rpp_a = ra.get("achilles_like", {}).get("records_per_person", {})
    rpp_b = rb.get("achilles_like", {}).get("records_per_person", {})
    rpp_data_a = list(zip(rpp_a.get("records_per_person", []), rpp_a.get("n_persons", [])))
    rpp_data_b = list(zip(rpp_b.get("records_per_person", []), rpp_b.get("n_persons", [])))
    if rpp_data_a or rpp_data_b:
        html += f'<h3>{_esc(L["records_per_person"])}</h3>\n'
        html += _svg_bar_chart_overlay(rpp_data_a, rpp_data_b, label_a, label_b, width=1100, height=220)

    # Top concepts side-by-side
    concepts_a = ra.get("achilles_like", {}).get("top_concepts", [])
    concepts_b = rb.get("achilles_like", {}).get("top_concepts", [])
    if concepts_a or concepts_b:
        html += f'<h3>{_esc(L["top_concepts"])}</h3>\n'
        html += '<div class="side-by-side">\n'
        for label, concepts in [(label_a, concepts_a), (label_b, concepts_b)]:
            html += f'<div><h4 style="margin-bottom:8px">{_esc(label)}</h4>\n'
            html += f'<table><tr><th>{L["concept_id"]}</th><th>{L["concept_name"]}</th><th>{L["n_records"]}</th><th>{L["n_persons"]}</th></tr>\n'
            for c in concepts[:20]:
                html += f'<tr><td>{_esc(c.get("concept_id", ""))}</td><td>{_esc(c.get("concept_name", ""))}</td>'
                html += f'<td>{c.get("n_records", 0):,}</td><td>{c.get("n_persons", 0):,}</td></tr>\n'
            html += '</table></div>\n'
        html += '</div>\n'

    # Top unmapped side-by-side
    unmapped_a = ma.get("top_unmapped_terms", [])
    unmapped_b = mb.get("top_unmapped_terms", [])
    if unmapped_a or unmapped_b:
        html += f'<h3>{_esc(L["top_unmapped"])}</h3>\n'
        html += '<div class="side-by-side">\n'
        for label, unmapped in [(label_a, unmapped_a), (label_b, unmapped_b)]:
            html += f'<div><h4 style="margin-bottom:8px">{_esc(label)}</h4>\n'
            html += f'<table><tr><th>{L["source_value"]}</th><th>{L["occurrences"]}</th></tr>\n'
            for u in unmapped[:20]:
                html += f'<tr><td>{_esc(u.get("source_value", ""))}</td><td>{u.get("count", 0):,}</td></tr>\n'
            html += '</table></div>\n'
        html += '</div>\n'

    return html
