"""
Cohort Comparison Engine — SMD (Standardized Mean Difference) computation.

Takes two CharacterizationResult dicts and computes SMD for every variable:
  - Continuous: (mean_A - mean_B) / sqrt((sd_A² + sd_B²) / 2)
  - Binary:    (p_A - p_B) / sqrt((p_A*(1-p_A) + p_B*(1-p_B)) / 2)
"""
import math
from typing import Any


def compute_smd_continuous(
    mean_a: float | None, sd_a: float | None,
    mean_b: float | None, sd_b: float | None,
) -> float | None:
    """SMD for continuous variables."""
    if mean_a is None or mean_b is None:
        return None
    sa = sd_a or 0.0
    sb = sd_b or 0.0
    denom_sq = (sa ** 2 + sb ** 2) / 2.0
    if denom_sq == 0:
        return 0.0 if mean_a == mean_b else None
    return (mean_a - mean_b) / math.sqrt(denom_sq)


def compute_smd_binary(p_a: float, p_b: float) -> float | None:
    """SMD for binary/proportional variables. p values in 0-1 range."""
    denom_sq = (p_a * (1 - p_a) + p_b * (1 - p_b)) / 2.0
    if denom_sq <= 0:
        return 0.0 if p_a == p_b else None
    return (p_a - p_b) / math.sqrt(denom_sq)


def _safe_pct(pct: float | None) -> float:
    """Convert percentage (0-100) to proportion (0-1), default 0."""
    if pct is None:
        return 0.0
    return pct / 100.0


def _round_smd(smd: float | None) -> float | None:
    if smd is None:
        return None
    return round(smd, 4)


def compare_cohorts(char_a: dict, char_b: dict) -> dict:
    """
    Compare two CharacterizationResult dicts.
    Returns structured comparison with SMD for every variable.
    """
    size_a = char_a.get("cohort_size", 0)
    size_b = char_b.get("cohort_size", 0)

    all_vars: list[dict] = []

    # ── Demographics ──
    demo_a = char_a.get("demographics", {})
    demo_b = char_b.get("demographics", {})

    # Age (continuous)
    age_a = demo_a.get("age", {})
    age_b = demo_b.get("age", {})
    age_smd = compute_smd_continuous(
        age_a.get("mean_age"), age_a.get("std_age"),
        age_b.get("mean_age"), age_b.get("std_age"),
    )
    all_vars.append({"category": "Demographics", "variable": "Age (mean)", "smd": _round_smd(age_smd)})

    # Categorical demographics: gender, race, ethnicity
    def _compare_categorical(field: str, label_key: str = "label") -> list[dict]:
        items_a = {item[label_key]: item["count"] for item in demo_a.get(field, [])}
        items_b = {item[label_key]: item["count"] for item in demo_b.get(field, [])}
        all_labels = sorted(set(items_a.keys()) | set(items_b.keys()))
        rows = []
        for label in all_labels:
            pa = (items_a.get(label, 0) / size_a) if size_a > 0 else 0.0
            pb = (items_b.get(label, 0) / size_b) if size_b > 0 else 0.0
            smd = compute_smd_binary(pa, pb)
            rows.append({
                "label": label,
                "pct_a": round(pa * 100, 1),
                "pct_b": round(pb * 100, 1),
                "smd": _round_smd(smd),
            })
            all_vars.append({
                "category": "Demographics",
                "variable": f"{field.capitalize()}: {label}",
                "smd": _round_smd(smd),
            })
        return rows

    gender_rows = _compare_categorical("gender")
    race_rows = _compare_categorical("race")
    ethnicity_rows = _compare_categorical("ethnicity")

    # Age groups
    groups_a = {g["age_group"]: g["count"] for g in demo_a.get("age_groups", [])}
    groups_b = {g["age_group"]: g["count"] for g in demo_b.get("age_groups", [])}
    all_groups = sorted(set(groups_a.keys()) | set(groups_b.keys()))
    age_group_rows = []
    for ag in all_groups:
        pa = (groups_a.get(ag, 0) / size_a) if size_a > 0 else 0.0
        pb = (groups_b.get(ag, 0) / size_b) if size_b > 0 else 0.0
        smd = compute_smd_binary(pa, pb)
        age_group_rows.append({
            "label": ag, "age_group": ag,
            "pct_a": round(pa * 100, 1),
            "pct_b": round(pb * 100, 1),
            "smd": _round_smd(smd),
        })
        all_vars.append({
            "category": "Demographics",
            "variable": f"Age group: {ag}",
            "smd": _round_smd(smd),
        })

    demographics = {
        "age": {
            "mean_a": age_a.get("mean_age"),
            "std_a": age_a.get("std_age"),
            "mean_b": age_b.get("mean_age"),
            "std_b": age_b.get("std_age"),
            "smd": _round_smd(age_smd),
        },
        "gender": gender_rows,
        "race": race_rows,
        "ethnicity": ethnicity_rows,
        "age_groups": age_group_rows,
    }

    # ── Domain Prevalence ──
    dp_a_map = {d["domain"]: d for d in char_a.get("domain_prevalence", [])}
    dp_b_map = {d["domain"]: d for d in char_b.get("domain_prevalence", [])}
    all_domains = sorted(set(dp_a_map.keys()) | set(dp_b_map.keys()))

    domain_prevalence = []
    for domain in all_domains:
        da = dp_a_map.get(domain, {"pct_with_data": 0, "top_concepts": []})
        db = dp_b_map.get(domain, {"pct_with_data": 0, "top_concepts": []})

        pct_a = _safe_pct(da.get("pct_with_data", 0))
        pct_b = _safe_pct(db.get("pct_with_data", 0))
        domain_smd = compute_smd_binary(pct_a, pct_b)

        all_vars.append({
            "category": domain,
            "variable": f"{domain}: any data",
            "smd": _round_smd(domain_smd),
        })

        # Union of top concepts
        concepts_a = {c["concept_id"]: c for c in da.get("top_concepts", [])}
        concepts_b = {c["concept_id"]: c for c in db.get("top_concepts", [])}
        all_cids = sorted(set(concepts_a.keys()) | set(concepts_b.keys()))

        concept_rows = []
        for cid in all_cids:
            ca = concepts_a.get(cid, {})
            cb = concepts_b.get(cid, {})
            pa = _safe_pct(ca.get("pct_persons", 0))
            pb = _safe_pct(cb.get("pct_persons", 0))
            csmd = compute_smd_binary(pa, pb)
            name = ca.get("concept_name") or cb.get("concept_name", "Unknown")
            concept_rows.append({
                "concept_id": cid,
                "concept_name": name,
                "pct_persons_a": round(pa * 100, 1),
                "pct_persons_b": round(pb * 100, 1),
                "smd": _round_smd(csmd),
            })
            all_vars.append({
                "category": domain,
                "variable": name,
                "smd": _round_smd(csmd),
            })

        # Sort by max prevalence descending
        concept_rows.sort(key=lambda r: max(r["pct_persons_a"], r["pct_persons_b"]), reverse=True)

        domain_prevalence.append({
            "domain": domain,
            "pct_with_data_a": round(pct_a * 100, 1),
            "pct_with_data_b": round(pct_b * 100, 1),
            "smd": _round_smd(domain_smd),
            "concepts": concept_rows,
        })

    # ── Measurement Stats ──
    meas_a = {m["concept_id"]: m for m in char_a.get("measurement_stats", [])}
    meas_b = {m["concept_id"]: m for m in char_b.get("measurement_stats", [])}
    all_meas = sorted(set(meas_a.keys()) | set(meas_b.keys()))

    measurement_rows = []
    for cid in all_meas:
        ma = meas_a.get(cid, {})
        mb = meas_b.get(cid, {})
        name = ma.get("concept_name") or mb.get("concept_name", "Unknown")
        unit = ma.get("unit") or mb.get("unit", "")

        val_smd = compute_smd_continuous(
            ma.get("mean_value"), ma.get("std_value"),
            mb.get("mean_value"), mb.get("std_value"),
        )
        pa = _safe_pct(ma.get("pct_persons", 0))
        pb = _safe_pct(mb.get("pct_persons", 0))
        prev_smd = compute_smd_binary(pa, pb)

        measurement_rows.append({
            "concept_id": cid,
            "concept_name": name,
            "unit": unit,
            "mean_a": ma.get("mean_value"),
            "std_a": ma.get("std_value"),
            "mean_b": mb.get("mean_value"),
            "std_b": mb.get("std_value"),
            "smd": _round_smd(val_smd),
            "pct_persons_a": round(pa * 100, 1),
            "pct_persons_b": round(pb * 100, 1),
            "prevalence_smd": _round_smd(prev_smd),
        })
        all_vars.append({
            "category": "Measurement",
            "variable": f"{name} (value)",
            "smd": _round_smd(val_smd),
        })

    measurement_rows.sort(
        key=lambda r: max(r["pct_persons_a"], r["pct_persons_b"]), reverse=True
    )

    # ── Visit Types ──
    vt_a = {v["concept_id"]: v for v in char_a.get("visit_types", [])}
    vt_b = {v["concept_id"]: v for v in char_b.get("visit_types", [])}
    all_vt = sorted(set(vt_a.keys()) | set(vt_b.keys()))

    visit_rows = []
    for cid in all_vt:
        va = vt_a.get(cid, {})
        vb = vt_b.get(cid, {})
        name = va.get("concept_name") or vb.get("concept_name", "Unknown")
        pa = _safe_pct(va.get("pct_persons", 0))
        pb = _safe_pct(vb.get("pct_persons", 0))
        vsmd = compute_smd_binary(pa, pb)
        visit_rows.append({
            "concept_id": cid,
            "concept_name": name,
            "pct_persons_a": round(pa * 100, 1),
            "pct_persons_b": round(pb * 100, 1),
            "smd": _round_smd(vsmd),
        })
        all_vars.append({
            "category": "Visit",
            "variable": f"Visit: {name}",
            "smd": _round_smd(vsmd),
        })

    visit_rows.sort(key=lambda r: max(r["pct_persons_a"], r["pct_persons_b"]), reverse=True)

    # ── Observation Period ──
    obs_a = char_a.get("observation_period", {})
    obs_b = char_b.get("observation_period", {})
    obs_smd = compute_smd_continuous(
        obs_a.get("mean_days"), obs_a.get("std_days"),
        obs_b.get("mean_days"), obs_b.get("std_days"),
    )
    all_vars.append({
        "category": "Observation Period",
        "variable": "Observation duration (days)",
        "smd": _round_smd(obs_smd),
    })

    return {
        "cohort_a_size": size_a,
        "cohort_b_size": size_b,
        "demographics": demographics,
        "domain_prevalence": domain_prevalence,
        "measurement_stats": measurement_rows,
        "visit_types": visit_rows,
        "observation_period": {
            "mean_days_a": obs_a.get("mean_days"),
            "std_days_a": obs_a.get("std_days"),
            "mean_days_b": obs_b.get("mean_days"),
            "std_days_b": obs_b.get("std_days"),
            "smd": _round_smd(obs_smd),
        },
        "all_variables": all_vars,
    }
