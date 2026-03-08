"""
Cohort JSON → SQL translation engine.

Translates a structured cohort criteria JSON into optimized PostgreSQL
using CTEs, temporal joins, and concept_ancestor expansion.
"""
import logging
import re

from config import DOMAIN_CONFIG

# Strict pattern for OMOP schema names: only alphanumeric and underscores
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Strict ISO date pattern
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_identifier(name: str) -> str:
    """Validate and return a safe SQL identifier (schema/table/column name)."""
    if not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


def _validate_date_string(date_str: str) -> str:
    """Validate that a string is a safe ISO date (YYYY-MM-DD)."""
    if not _DATE_RE.match(date_str):
        raise ValueError(f"Invalid date format: {date_str!r}. Expected YYYY-MM-DD.")
    return date_str

logger = logging.getLogger(__name__)

# Mapping from domain names to OMOP table metadata
_DOMAIN_TABLE_MAP = {
    name: {
        "table": cfg["table"],
        "person_id": cfg["person_id"],
        "concept_id": cfg["concept_id"],
        "date_col": cfg["date_col"],
        "source_value": cfg.get("source_value"),
        "source_name": cfg.get("source_name"),
    }
    for name, cfg in DOMAIN_CONFIG.items()
}

# End-date columns for domains that have them (temporal relations)
_DOMAIN_END_DATE = {
    "Condition": "condition_end_date",
    "Drug": "drug_exposure_end_date",
    "Visit": "visit_end_date",
    "Device": "device_exposure_end_date",
}

# SQL conditions for Allen's temporal relations
# Uses event_date (start) and event_end_date (end, may be NULL) from CTEs
_TEMPORAL_RELATION_SQL = {
    'before':        "a.event_date < ref.event_date",
    'after':         "a.event_date > ref.event_date",
    'starts_before': "a.event_date < ref.event_date",
    'starts_after':  "a.event_date > ref.event_date",
    'ends_before':   "COALESCE(a.event_end_date, a.event_date) < COALESCE(ref.event_end_date, ref.event_date)",
    'ends_after':    "COALESCE(a.event_end_date, a.event_date) > COALESCE(ref.event_end_date, ref.event_date)",
    'overlaps':      "a.event_date < COALESCE(ref.event_end_date, ref.event_date) AND COALESCE(a.event_end_date, a.event_date) > ref.event_date",
    'contains':      "a.event_date <= ref.event_date AND COALESCE(a.event_end_date, a.event_date) >= COALESCE(ref.event_end_date, ref.event_date)",
    'during':        "a.event_date >= ref.event_date AND COALESCE(a.event_end_date, a.event_date) <= COALESCE(ref.event_end_date, ref.event_date)",
}


def build_cohort_sql(
    criteria: dict, omop_schema: str = "omop_cdm", include_visit_id: bool = False,
) -> str:
    """
    Build a complete SQL query from a cohort criteria JSON object.

    Returns a SQL string that yields a list of person_id values matching
    the cohort definition.

    When include_visit_id=True and sameVisit is enabled on the inclusion group,
    the output includes visit_occurrence_id alongside person_id — useful for
    visit-level characterization.
    """
    _validate_identifier(omop_schema)
    ctes: list[str] = []
    cte_names: list[str] = []
    cte_counter = [0]
    criterion_cte_map: dict[str, str] = {}  # criterion UUID → CTE name

    def next_cte_name(prefix: str = "cte") -> str:
        cte_counter[0] += 1
        return f"{prefix}_{cte_counter[0]}"

    # Determine whether visit_occurrence_id will be in the output
    has_same_visit = bool(
        criteria.get("inclusion", {}).get("sameVisit", False)
    )
    visit_in_output = include_visit_id and has_same_visit

    # --- Build inclusion criteria ---
    inclusion = criteria.get("inclusion")
    inc_cte = None
    inc_attrition: list[dict] = []
    if inclusion and (inclusion.get("criteria") or inclusion.get("groups")):
        inc_cte, inc_parts = _build_group(
            inclusion, omop_schema, ctes, cte_names, next_cte_name, "inc",
            inc_attrition, keep_visit_id=visit_in_output,
            criterion_cte_map=criterion_cte_map,
        )

    # --- Build exclusion criteria ---
    exclusion = criteria.get("exclusion")
    exc_cte = None
    exc_attrition: list[dict] = []
    if exclusion and (exclusion.get("criteria") or exclusion.get("groups")):
        exc_cte, exc_parts = _build_group(
            exclusion, omop_schema, ctes, cte_names, next_cte_name, "exc", exc_attrition,
            criterion_cte_map=criterion_cte_map,
        )

    # --- Demographics filter ---
    demo = criteria.get("demographics")
    demo_cte = None
    if demo:
        demo_cte = _build_demographics_cte(
            demo, omop_schema, ctes, cte_names, next_cte_name
        )

    # --- Assemble final query ---
    if not inc_cte and not demo_cte:
        # No criteria at all — return all persons
        return f"SELECT person_id FROM {omop_schema}.person"

    select_cols = "person_id, visit_occurrence_id" if visit_in_output else "person_id"

    final_parts = []
    if inc_cte:
        final_parts.append(inc_cte)
    if demo_cte:
        final_parts.append(demo_cte)

    if len(final_parts) == 1:
        base = final_parts[0]
    elif visit_in_output:
        # Can't INTERSECT with different column counts; use WHERE IN instead
        base_name = next_cte_name("base")
        base_sql = (
            f"{base_name} AS (\n"
            f"  SELECT {select_cols} FROM {final_parts[0]}\n"
            f"  WHERE person_id IN (SELECT person_id FROM {final_parts[1]})\n"
            f")"
        )
        ctes.append(base_sql)
        cte_names.append(base_name)
        base = base_name
    else:
        # INTERSECT inclusion + demographics
        base_name = next_cte_name("base")
        base_sql = (
            f"{base_name} AS (\n"
            f"  SELECT person_id FROM {final_parts[0]}\n"
            f"  INTERSECT\n"
            f"  SELECT person_id FROM {final_parts[1]}\n"
            f")"
        )
        ctes.append(base_sql)
        cte_names.append(base_name)
        base = base_name

    # Apply exclusion
    if exc_cte:
        final_name = next_cte_name("final")
        if visit_in_output:
            final_sql = (
                f"{final_name} AS (\n"
                f"  SELECT {select_cols} FROM {base}\n"
                f"  WHERE person_id NOT IN (SELECT person_id FROM {exc_cte})\n"
                f")"
            )
        else:
            final_sql = (
                f"{final_name} AS (\n"
                f"  SELECT person_id FROM {base}\n"
                f"  EXCEPT\n"
                f"  SELECT person_id FROM {exc_cte}\n"
                f")"
            )
        ctes.append(final_sql)
        cte_names.append(final_name)
        result_cte = final_name
    else:
        result_cte = base

    # Build the full WITH ... SELECT statement
    if ctes:
        with_clause = "WITH\n" + ",\n".join(ctes)
        return f"{with_clause}\nSELECT {select_cols} FROM {result_cte}"
    else:
        return f"SELECT {select_cols} FROM {result_cte}"


def build_count_sql(criteria: dict, omop_schema: str = "omop_cdm") -> str:
    """Build a SQL query that returns only the count of matching patients."""
    inner = build_cohort_sql(criteria, omop_schema)
    return f"SELECT COUNT(DISTINCT person_id) AS patient_count FROM ({inner}) AS cohort"


def build_attrition_sql(criteria: dict, omop_schema: str = "omop_cdm") -> list[dict]:
    """
    Build a list of SQL queries for attrition analysis.
    Each step returns a cumulative count as criteria are added one by one.
    Returns list of {step, label, sql} dicts.
    """
    steps = []
    inclusion = criteria.get("inclusion", {})
    exclusion = criteria.get("exclusion", {})
    demographics = criteria.get("demographics")

    # Step 0: all persons
    steps.append({
        "step": 0,
        "label": "All persons",
        "sql": f"SELECT COUNT(DISTINCT person_id) AS n FROM {omop_schema}.person",
    })

    # Accumulate inclusion criteria
    inc_criteria = inclusion.get("criteria", [])
    inc_operator = inclusion.get("operator", "AND")
    for i, criterion in enumerate(inc_criteria):
        partial = {
            "operator": inc_operator,
            "criteria": inc_criteria[: i + 1],
        }
        partial_full = {"inclusion": partial}
        if demographics:
            partial_full["demographics"] = demographics
        sql = build_count_sql(partial_full, omop_schema)
        label = _criterion_label(criterion)
        steps.append({"step": i + 1, "label": f"+ {label}", "sql": sql})

    # Exclusion criteria
    exc_criteria = exclusion.get("criteria", [])
    if exc_criteria:
        for j, criterion in enumerate(exc_criteria):
            partial_exc = {
                "operator": exclusion.get("operator", "OR"),
                "criteria": exc_criteria[: j + 1],
            }
            partial_full = {"inclusion": inclusion, "exclusion": partial_exc}
            if demographics:
                partial_full["demographics"] = demographics
            sql = build_count_sql(partial_full, omop_schema)
            label = _criterion_label(criterion)
            base_step = len(inc_criteria) + 1
            steps.append({"step": base_step + j, "label": f"- {label}", "sql": sql})

    return steps


def build_sample_sql(
    criteria: dict, omop_schema: str = "omop_cdm", limit: int = 10
) -> str:
    """Build SQL to return a random sample of patient data from the cohort."""
    inner = build_cohort_sql(criteria, omop_schema)
    return (
        f"WITH cohort AS ({inner})\n"
        f"SELECT p.person_id, p.year_of_birth,\n"
        f"       COALESCE(g.concept_name, 'UNKNOWN') AS gender,\n"
        f"       COALESCE(r.concept_name, 'UNKNOWN') AS race,\n"
        f"       op.observation_period_start_date,\n"
        f"       op.observation_period_end_date\n"
        f"FROM cohort c\n"
        f"JOIN {omop_schema}.person p ON c.person_id = p.person_id\n"
        f"LEFT JOIN {omop_schema}.concept g ON p.gender_concept_id = g.concept_id\n"
        f"LEFT JOIN {omop_schema}.concept r ON p.race_concept_id = r.concept_id\n"
        f"LEFT JOIN LATERAL (\n"
        f"  SELECT observation_period_start_date, observation_period_end_date\n"
        f"  FROM {omop_schema}.observation_period\n"
        f"  WHERE person_id = c.person_id\n"
        f"  ORDER BY observation_period_start_date DESC LIMIT 1\n"
        f") op ON TRUE\n"
        f"ORDER BY RANDOM()\n"
        f"LIMIT {int(limit)}"
    )


def build_detailed_sample_sql(
    criteria: dict, omop_schema: str = "omop_cdm", limit: int = 10
) -> tuple[str, list[dict]]:
    """
    Build SQL returning a detailed patient sample with per-criterion matched codes.

    Returns (sql, columns_meta) where columns_meta describes the dynamic columns
    so the frontend knows how to label them.
    Each row has: person_id, year_of_birth, [visit_occurrence_id if sameVisit],
    and for each inclusion criterion: crit_<i>_code, crit_<i>_value (if Measurement).
    """
    inner = build_cohort_sql(criteria, omop_schema)

    inclusion = criteria.get("inclusion", {})
    inc_criteria = inclusion.get("criteria", [])
    same_visit = inclusion.get("sameVisit", False)

    # Build LATERAL joins for each criterion
    laterals = []
    select_extra = []
    columns_meta = []

    for i, criterion in enumerate(inc_criteria):
        domain = criterion.get("domain", "")
        if domain not in _DOMAIN_TABLE_MAP:
            continue

        dmeta = _DOMAIN_TABLE_MAP[domain]
        full_table = f"{omop_schema}.{dmeta['table']}"
        pid_col = dmeta["person_id"]
        concept_col = dmeta["concept_id"]
        source_value_col = dmeta.get("source_value")
        source_name_col = dmeta.get("source_name")
        alias = f"cr{i}"

        # Build WHERE for this criterion's concept/source filters
        concepts = criterion.get("concepts", [])
        source_codes = criterion.get("source_codes", [])
        wheres = []

        concept_filter = None
        if concepts:
            use_descendants = criterion.get("include_descendants", True)
            concept_list = ", ".join(
                str(int(c["concept_id"] if isinstance(c, dict) else c)) for c in concepts
            )
            if use_descendants:
                ancestor_subq = (
                    f"SELECT descendant_concept_id FROM {omop_schema}.concept_ancestor "
                    f"WHERE ancestor_concept_id IN ({concept_list})"
                )
                concept_filter = f"t.{concept_col} IN ({ancestor_subq})"
            else:
                concept_filter = f"t.{concept_col} IN ({concept_list})"

        source_filter = None
        if source_codes and source_value_col:
            escaped = ", ".join(
                f"'{code.replace(chr(39), chr(39)+chr(39))}'" for code in source_codes
            )
            source_filter = f"t.{source_value_col} IN ({escaped})"

        if concept_filter and source_filter:
            wheres.append(f"({concept_filter} OR {source_filter})")
        elif concept_filter:
            wheres.append(concept_filter)
        elif source_filter:
            wheres.append(source_filter)

        if not wheres:
            continue

        where_clause = " AND ".join(wheres)

        # Build the select columns for this lateral
        is_measurement = (domain == "Measurement")
        lat_select = f"con.concept_code, con.concept_name"
        if source_name_col:
            lat_select += f", t.{source_name_col} AS source_name"
        if source_value_col:
            lat_select += f", t.{source_value_col} AS source_value"
        if is_measurement:
            lat_select += ", t.value_as_number, t.unit_source_value"
        if same_visit:
            lat_select += ", t.visit_occurrence_id"

        lateral_sql = (
            f"LEFT JOIN LATERAL (\n"
            f"  SELECT {lat_select}\n"
            f"  FROM {full_table} t\n"
            f"  LEFT JOIN {omop_schema}.concept con ON t.{concept_col} = con.concept_id\n"
            f"  WHERE t.{pid_col} = c.person_id AND {where_clause}\n"
            f"  LIMIT 1\n"
            f") {alias} ON TRUE"
        )
        laterals.append(lateral_sql)

        # Label for this criterion
        label = domain
        if concepts:
            names = [c.get("concept_name", "") if isinstance(c, dict) else str(c) for c in concepts[:2]]
            label = ", ".join(n for n in names if n) or domain
            if len(concepts) > 2:
                label += f" +{len(concepts)-2}"
        elif source_codes:
            label = ", ".join(source_codes[:2])
            if len(source_codes) > 2:
                label += f" +{len(source_codes)-2}"

        # source_code — label format: source_value then label (source_name > concept_name > ref codebook later)
        # Build the label expression: prioritize source_name (local) over concept_name (OMOP)
        if source_name_col:
            label_expr = f"COALESCE({alias}.source_name, {alias}.concept_name)"
        else:
            label_expr = f"{alias}.concept_name"

        if source_value_col:
            select_extra.append(
                f"COALESCE({alias}.source_value, {alias}.concept_code) || "
                f"COALESCE(' — ' || NULLIF({label_expr}, ''), '') AS crit_{i}_code"
            )
        else:
            select_extra.append(
                f"{alias}.concept_code || "
                f"COALESCE(' — ' || NULLIF({label_expr}, ''), '') AS crit_{i}_code"
            )
        columns_meta.append({"key": f"crit_{i}_code", "label": label, "domain": domain})

        if is_measurement:
            select_extra.append(
                f"CAST({alias}.value_as_number AS TEXT) || "
                f"COALESCE(' — ' || {alias}.unit_source_value, '') AS crit_{i}_value"
            )
            columns_meta.append({"key": f"crit_{i}_value", "label": f"{label} (value)", "domain": domain})

        if same_visit:
            # Only add visit_id once from the first criterion
            if i == 0:
                select_extra.insert(0, f"{alias}.visit_occurrence_id")
                columns_meta.insert(0, {"key": "visit_occurrence_id", "label": "Visit ID", "domain": ""})

    extra_cols = (", " + ", ".join(select_extra)) if select_extra else ""
    lateral_joins = "\n".join(laterals)

    sql = (
        f"WITH cohort AS ({inner})\n"
        f"SELECT p.person_id, p.year_of_birth{extra_cols}\n"
        f"FROM (SELECT DISTINCT person_id FROM cohort) c\n"
        f"JOIN {omop_schema}.person p ON c.person_id = p.person_id\n"
        f"{lateral_joins}\n"
        f"ORDER BY RANDOM()\n"
        f"LIMIT {int(limit)}"
    )
    return sql, columns_meta


def build_export_sql(criteria: dict, omop_schema: str = "omop_cdm") -> str:
    """Build SQL to export all patients with demographics (no limit, no random)."""
    inner = build_cohort_sql(criteria, omop_schema)
    return (
        f"WITH cohort AS ({inner})\n"
        f"SELECT p.person_id, p.year_of_birth,\n"
        f"       COALESCE(g.concept_name, 'UNKNOWN') AS gender,\n"
        f"       COALESCE(r.concept_name, 'UNKNOWN') AS race,\n"
        f"       op.observation_period_start_date,\n"
        f"       op.observation_period_end_date\n"
        f"FROM cohort c\n"
        f"JOIN {omop_schema}.person p ON c.person_id = p.person_id\n"
        f"LEFT JOIN {omop_schema}.concept g ON p.gender_concept_id = g.concept_id\n"
        f"LEFT JOIN {omop_schema}.concept r ON p.race_concept_id = r.concept_id\n"
        f"LEFT JOIN LATERAL (\n"
        f"  SELECT observation_period_start_date, observation_period_end_date\n"
        f"  FROM {omop_schema}.observation_period\n"
        f"  WHERE person_id = c.person_id\n"
        f"  ORDER BY observation_period_start_date DESC LIMIT 1\n"
        f") op ON TRUE\n"
        f"ORDER BY p.person_id"
    )


# ----------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------

def _build_group(
    group: dict,
    omop_schema: str,
    ctes: list[str],
    cte_names: list[str],
    next_cte_name,
    prefix: str,
    attrition: list[dict],
    keep_visit_id: bool = False,
    criterion_cte_map: dict | None = None,
) -> tuple[str, list[str]]:
    """
    Build CTEs for a logical group of criteria with nested sub-groups.

    Handles both flat criteria[] and nested groups[] simultaneously.
    Supports per-criterion operators via 'operatorWithNext' field.
    Returns (result_cte_name, list_of_individual_cte_names).
    """
    criteria = group.get("criteria", [])
    sub_groups = group.get("groups", [])
    operator = group.get("operator", "AND").upper()
    same_visit = group.get("sameVisit", False)

    criteria_cte = None
    criteria_parts = []

    # ── Process flat criteria ──
    if criteria:
        criteria_cte, criteria_parts = _build_criteria_flat(
            criteria, omop_schema, ctes, cte_names, next_cte_name,
            prefix, operator, same_visit, keep_visit_id, criterion_cte_map,
        )

    # ── Process nested sub-groups recursively ──
    sub_ctes = []
    for i, sg in enumerate(sub_groups):
        sub_cte, _ = _build_group(
            sg, omop_schema, ctes, cte_names, next_cte_name,
            f"{prefix}_g{i}", [], criterion_cte_map=criterion_cte_map,
        )
        if sub_cte:
            sub_ctes.append(sub_cte)

    # ── Combine criteria result with sub-group results ──
    all_parts = []
    if criteria_cte:
        all_parts.append(criteria_cte)
    all_parts.extend(sub_ctes)

    if not all_parts:
        return None, []
    if len(all_parts) == 1:
        return all_parts[0], criteria_parts + sub_ctes

    # Multiple parts: combine with the group operator
    set_op = "INTERSECT" if operator == "AND" else "UNION"
    combined_name = next_cte_name(f"{prefix}_grp")
    parts_sql = f"\n  {set_op}\n".join(
        f"  SELECT person_id FROM {n}" for n in all_parts
    )
    combined = f"{combined_name} AS (\n{parts_sql}\n)"
    ctes.append(combined)
    cte_names.append(combined_name)
    return combined_name, criteria_parts + sub_ctes


def _build_criteria_flat(
    criteria: list[dict],
    omop_schema: str,
    ctes: list[str],
    cte_names: list[str],
    next_cte_name,
    prefix: str,
    operator: str,
    same_visit: bool,
    keep_visit_id: bool,
    criterion_cte_map: dict | None,
) -> tuple[str | None, list[str]]:
    """
    Build CTEs for a flat list of criteria (no sub-groups).

    Supports per-criterion operators via 'operatorWithNext' field.
    Criteria linked by OR are grouped into sub-groups (UNION),
    then all groups are combined with AND (INTERSECT).
    """
    has_per_criterion_ops = any(c.get("operatorWithNext") for c in criteria)

    if has_per_criterion_ops:
        # Group consecutive OR-linked criteria together
        or_groups: list[list[dict]] = [[]]
        for i, criterion in enumerate(criteria):
            or_groups[-1].append(criterion)
            if i < len(criteria) - 1:
                op = criterion.get("operatorWithNext", "AND").upper()
                if op == "AND":
                    or_groups.append([])

        group_ctes = []
        select_cols = "person_id, visit_occurrence_id" if same_visit else "person_id"
        for gi, or_group in enumerate(or_groups):
            if len(or_group) == 1:
                cte_name = next_cte_name(prefix)
                cte = _build_criterion_cte(
                    or_group[0], omop_schema, cte_name, ctes, cte_names,
                    next_cte_name, include_visit_id=same_visit,
                    criterion_cte_map=criterion_cte_map,
                )
                group_ctes.append(cte)
            else:
                sub_ctes = []
                for c in or_group:
                    cte_name = next_cte_name(prefix)
                    cte = _build_criterion_cte(
                        c, omop_schema, cte_name, ctes, cte_names,
                        next_cte_name, include_visit_id=same_visit,
                        criterion_cte_map=criterion_cte_map,
                    )
                    sub_ctes.append(cte)
                union_name = next_cte_name(f"{prefix}_or")
                union_sql = f"\n  UNION\n".join(f"  SELECT {select_cols} FROM {n}" for n in sub_ctes)
                union_cte = f"{union_name} AS (\n{union_sql}\n)"
                ctes.append(union_cte)
                cte_names.append(union_name)
                group_ctes.append(union_name)

        if len(group_ctes) == 1:
            return group_ctes[0], group_ctes

        if same_visit and len(group_ctes) >= 2:
            combined_name = next_cte_name(f"{prefix}_samevisit")
            first = group_ctes[0]
            sv_cols = "a.person_id, a.visit_occurrence_id" if keep_visit_id else "a.person_id"
            join_sql = f"  SELECT DISTINCT {sv_cols}\n  FROM {first} a\n"
            for j, gc in enumerate(group_ctes[1:], 1):
                alias = chr(ord('a') + j)
                join_sql += f"  JOIN {gc} {alias} ON a.person_id = {alias}.person_id AND a.visit_occurrence_id = {alias}.visit_occurrence_id\n"
            combined = f"{combined_name} AS (\n{join_sql})"
            ctes.append(combined)
            cte_names.append(combined_name)
            return combined_name, group_ctes
        else:
            combined_name = next_cte_name(f"{prefix}_combined")
            parts_sql = f"\n  INTERSECT\n".join(f"  SELECT person_id FROM {n}" for n in group_ctes)
            combined = f"{combined_name} AS (\n{parts_sql}\n)"
            ctes.append(combined)
            cte_names.append(combined_name)
            return combined_name, group_ctes
    else:
        part_names = []
        for criterion in criteria:
            cte_name = next_cte_name(prefix)
            sql = _build_criterion_cte(
                criterion, omop_schema, cte_name, ctes, cte_names,
                next_cte_name, include_visit_id=same_visit,
                criterion_cte_map=criterion_cte_map,
            )
            part_names.append(sql)

        if len(part_names) == 0:
            return None, []
        if len(part_names) == 1:
            return part_names[0], part_names

        if same_visit and operator == "AND" and len(part_names) >= 2:
            combined_name = next_cte_name(f"{prefix}_samevisit")
            first = part_names[0]
            sv_cols = "a.person_id, a.visit_occurrence_id" if keep_visit_id else "a.person_id"
            join_sql = f"  SELECT DISTINCT {sv_cols}\n  FROM {first} a\n"
            for j, pn in enumerate(part_names[1:], 1):
                alias = chr(ord('a') + j)
                join_sql += f"  JOIN {pn} {alias} ON a.person_id = {alias}.person_id AND a.visit_occurrence_id = {alias}.visit_occurrence_id\n"
            combined = f"{combined_name} AS (\n{join_sql})"
            ctes.append(combined)
            cte_names.append(combined_name)
            return combined_name, part_names
        else:
            set_op = "INTERSECT" if operator == "AND" else "UNION"
            combined_name = next_cte_name(f"{prefix}_combined")
            parts_sql = f"\n  {set_op}\n".join(f"  SELECT person_id FROM {n}" for n in part_names)
            combined = f"{combined_name} AS (\n{parts_sql}\n)"
            ctes.append(combined)
            cte_names.append(combined_name)
            return combined_name, part_names


def _build_criterion_cte(
    criterion: dict,
    omop_schema: str,
    cte_name: str,
    ctes: list[str],
    cte_names: list[str],
    next_cte_name,
    include_visit_id: bool = False,
    criterion_cte_map: dict | None = None,
) -> str:
    """
    Build a single criterion CTE that yields person_id values.
    When include_visit_id=True, also yields visit_occurrence_id for same-visit joins.
    Handles domain lookup, concept expansion, temporal/frequency/value constraints.
    """
    domain = criterion.get("domain", "")
    concepts = criterion.get("concepts", [])
    source_codes = criterion.get("source_codes", [])
    temporal = criterion.get("temporal", {})
    occurrence = criterion.get("occurrence", {})
    value = criterion.get("value", {})

    # Special case: nested cohort reference
    if criterion.get("nested_cohort_sql"):
        cte_sql = f"{cte_name} AS (\n  {criterion['nested_cohort_sql']}\n)"
        ctes.append(cte_sql)
        cte_names.append(cte_name)
        return cte_name

    # Get domain table info
    if domain not in _DOMAIN_TABLE_MAP:
        raise ValueError(f"Unknown domain: {domain}")

    dmeta = _DOMAIN_TABLE_MAP[domain]
    full_table = f"{omop_schema}.{dmeta['table']}"
    pid_col = dmeta["person_id"]
    concept_col = dmeta["concept_id"]
    date_col = dmeta["date_col"]
    source_value_col = dmeta.get("source_value")

    # Build WHERE clauses
    wheres: list[str] = []

    # Concept filtering (with optional descendant expansion)
    concept_filter = None
    if concepts:
        use_descendants = criterion.get("include_descendants", True)
        if use_descendants:
            concept_list = ", ".join(
                str(int(c["concept_id"] if isinstance(c, dict) else c)) for c in concepts
            )
            ancestor_subq = (
                f"SELECT descendant_concept_id FROM {omop_schema}.concept_ancestor "
                f"WHERE ancestor_concept_id IN ({concept_list})"
            )
            concept_filter = f"t.{concept_col} IN ({ancestor_subq})"
        else:
            concept_list = ", ".join(
                str(int(c["concept_id"] if isinstance(c, dict) else c)) for c in concepts
            )
            concept_filter = f"t.{concept_col} IN ({concept_list})"

    # Source code filtering (direct match on source_value column)
    source_filter = None
    if source_codes and source_value_col:
        escaped = ", ".join(
            f"'{code.replace(chr(39), chr(39)+chr(39))}'" for code in source_codes
        )
        source_filter = f"t.{source_value_col} IN ({escaped})"

    # Combine concept + source filters with OR
    if concept_filter and source_filter:
        wheres.append(f"({concept_filter} OR {source_filter})")
    elif concept_filter:
        wheres.append(concept_filter)
    elif source_filter:
        wheres.append(source_filter)

    # Temporal constraints
    temporal_type = temporal.get("type", "any_time")
    if temporal_type == "absolute_window":
        date_from = temporal.get("date_from")
        date_to = temporal.get("date_to")
        if date_from:
            _validate_date_string(date_from)
            wheres.append(f"t.{date_col} >= DATE '{date_from}'")
        if date_to:
            _validate_date_string(date_to)
            wheres.append(f"t.{date_col} <= DATE '{date_to}'")

    # Value constraints (mainly for Measurement)
    if value:
        val_op = value.get("operator")
        val_num = value.get("value")
        val_high = value.get("value_high")
        if val_op and val_num is not None:
            if val_op == "between" and val_high is not None:
                wheres.append(f"t.value_as_number BETWEEN {float(val_num)} AND {float(val_high)}")
            else:
                op_map = {">": ">", "<": "<", ">=": ">=", "<=": "<=", "=": "="}
                sql_op = op_map.get(val_op)
                if sql_op is None:
                    raise ValueError(f"Invalid value operator: {val_op!r}")
                wheres.append(f"t.value_as_number {sql_op} {float(val_num)}")
        val_concept = value.get("value_as_concept_id")
        if val_concept is not None:
            wheres.append(f"t.value_as_concept_id = {int(val_concept)}")
        unit_concept = value.get("unit_concept_id")
        if unit_concept is not None:
            wheres.append(f"t.unit_concept_id = {int(unit_concept)}")

    where_clause = " AND ".join(wheres) if wheres else "TRUE"

    # Visit column for same-visit joins
    visit_select = ", t.visit_occurrence_id" if include_visit_id else ""

    # Include event_date (and event_end_date when available) for temporal relations
    end_date_col = _DOMAIN_END_DATE.get(domain)
    event_date_select = f", MIN(t.{date_col}) AS event_date"
    if end_date_col:
        event_date_select += f", MAX(t.{end_date_col}) AS event_end_date"
    else:
        event_date_select += f", MIN(t.{date_col}) AS event_end_date"

    # Handle occurrence (frequency) constraints
    occ_type = occurrence.get("type")
    occ_count = occurrence.get("count", 1)

    if occ_type and occ_type != "any":
        # Need GROUP BY + HAVING for frequency
        occ_op_map = {
            "at_least": ">=",
            "exactly": "=",
            "at_most": "<=",
        }
        occ_op = occ_op_map.get(occ_type, ">=")

        # Occurrence within a window
        occ_window_days = occurrence.get("within_days")
        if occ_window_days:
            # Windowed frequency: N events within X days
            inner_name = next_cte_name("occ_inner")
            inner_sql = (
                f"{inner_name} AS (\n"
                f"  SELECT t.{pid_col} AS person_id, t.{date_col} AS event_date\n"
                f"  FROM {full_table} t\n"
                f"  WHERE {where_clause}\n"
                f")"
            )
            ctes.append(inner_sql)
            cte_names.append(inner_name)

            cte_sql = (
                f"{cte_name} AS (\n"
                f"  SELECT DISTINCT a.person_id, a.event_date\n"
                f"  FROM {inner_name} a\n"
                f"  WHERE (\n"
                f"    SELECT COUNT(*) FROM {inner_name} b\n"
                f"    WHERE b.person_id = a.person_id\n"
                f"      AND b.event_date BETWEEN a.event_date AND a.event_date + INTERVAL '{int(occ_window_days)} days'\n"
                f"  ) {occ_op} {int(occ_count)}\n"
                f")"
            )
        else:
            cte_sql = (
                f"{cte_name} AS (\n"
                f"  SELECT t.{pid_col} AS person_id{visit_select}{event_date_select}\n"
                f"  FROM {full_table} t\n"
                f"  WHERE {where_clause}\n"
                f"  GROUP BY t.{pid_col}{visit_select}\n"
                f"  HAVING COUNT(*) {occ_op} {int(occ_count)}\n"
                f")"
            )
    else:
        cte_sql = (
            f"{cte_name} AS (\n"
            f"  SELECT t.{pid_col} AS person_id{visit_select}{event_date_select}\n"
            f"  FROM {full_table} t\n"
            f"  WHERE {where_clause}\n"
            f"  GROUP BY t.{pid_col}{visit_select}\n"
            f")"
        )

    ctes.append(cte_sql)
    cte_names.append(cte_name)

    # Register criterion ID → CTE name for temporal reference lookups
    crit_id = criterion.get("id")
    if crit_id and criterion_cte_map is not None:
        criterion_cte_map[crit_id] = cte_name

    # Handle temporal relative constraints (within_days relative to index)
    if temporal_type == "within_days" and temporal.get("relative_to") == "index":
        # This requires the index event to be defined (first inclusion criterion)
        # For now, we wrap with an additional temporal join CTE
        days_before = temporal.get("days_before")
        days_after = temporal.get("days_after")
        if days_before or days_after:
            temp_name = next_cte_name("temporal")
            # The index event is the first event for each person in the criterion's domain
            temp_conditions = []
            if days_before:
                temp_conditions.append(
                    f"t.{date_col} >= (idx.index_date - INTERVAL '{int(days_before)} days')"
                )
            if days_after:
                temp_conditions.append(
                    f"t.{date_col} <= (idx.index_date + INTERVAL '{int(days_after)} days')"
                )
            temp_where = " AND ".join(temp_conditions)

            temp_sql = (
                f"{temp_name} AS (\n"
                f"  SELECT DISTINCT t.{pid_col} AS person_id\n"
                f"  FROM {full_table} t\n"
                f"  JOIN (\n"
                f"    SELECT person_id, MIN({date_col}) AS index_date\n"
                f"    FROM {full_table}\n"
                f"    WHERE {where_clause}\n"
                f"    GROUP BY person_id\n"
                f"  ) idx ON t.{pid_col} = idx.person_id\n"
                f"  WHERE {where_clause} AND {temp_where}\n"
                f")"
            )
            ctes.append(temp_sql)
            cte_names.append(temp_name)
            return temp_name

    # Handle temporal relative to another criterion (Allen's interval algebra)
    if temporal_type == "relative_to_criterion":
        ref_id = temporal.get("reference_criterion_id")
        relation = temporal.get("relation", "before")
        days_before = temporal.get("days_before")
        days_after = temporal.get("days_after")

        if ref_id:
            # Look up the reference criterion's CTE via the ID map
            ref_cte = None
            if criterion_cte_map:
                ref_cte = criterion_cte_map.get(ref_id)

            if not ref_cte:
                # Fallback: scan cte_names for a match
                for cn in cte_names:
                    if ref_id in cn:
                        ref_cte = cn
                        break

            if not ref_cte:
                logger.warning(
                    "Reference criterion CTE not found for id=%s, skipping temporal constraint",
                    ref_id,
                )
                return cte_name

            # Build temporal join conditions
            conditions = []

            # Allen's relation condition
            rel_sql = _TEMPORAL_RELATION_SQL.get(relation)
            if rel_sql:
                # Replace 'a.' with the current criterion CTE alias
                conditions.append(rel_sql)

            # Optional time window
            if days_before is not None:
                conditions.append(
                    f"a.event_date >= (ref.event_date - INTERVAL '{int(days_before)} days')"
                )
            if days_after is not None:
                conditions.append(
                    f"a.event_date <= (ref.event_date + INTERVAL '{int(days_after)} days')"
                )

            temp_where = " AND ".join(conditions) if conditions else "TRUE"

            temp_name = next_cte_name("rel_temporal")
            temp_sql = (
                f"{temp_name} AS (\n"
                f"  SELECT DISTINCT a.person_id\n"
                f"  FROM {cte_name} a\n"
                f"  JOIN {ref_cte} ref ON a.person_id = ref.person_id\n"
                f"  WHERE {temp_where}\n"
                f")"
            )
            ctes.append(temp_sql)
            cte_names.append(temp_name)

            # Update the criterion_cte_map to point to the temporal CTE
            if crit_id and criterion_cte_map is not None:
                criterion_cte_map[crit_id] = temp_name

            return temp_name

    return cte_name


def _build_demographics_cte(
    demo: dict,
    omop_schema: str,
    ctes: list[str],
    cte_names: list[str],
    next_cte_name,
) -> str:
    """Build a CTE for demographic constraints (age, gender, race)."""
    person_table = f"{omop_schema}.person"
    wheres: list[str] = []

    # Gender
    gender = demo.get("gender")
    if gender and isinstance(gender, list):
        glist = ", ".join(str(int(g)) for g in gender)
        wheres.append(f"p.gender_concept_id IN ({glist})")

    # Race
    race = demo.get("race")
    if race and isinstance(race, list):
        rlist = ", ".join(str(int(r)) for r in race)
        wheres.append(f"p.race_concept_id IN ({rlist})")

    # Ethnicity
    ethnicity = demo.get("ethnicity")
    if ethnicity and isinstance(ethnicity, list):
        elist = ", ".join(str(int(e)) for e in ethnicity)
        wheres.append(f"p.ethnicity_concept_id IN ({elist})")

    # Age
    age = demo.get("age")
    if age:
        age_min = age.get("min")
        age_max = age.get("max")
        # Calculate age based on year_of_birth vs current date
        age_expr = "EXTRACT(YEAR FROM CURRENT_DATE) - p.year_of_birth"
        if age_min is not None:
            wheres.append(f"({age_expr}) >= {int(age_min)}")
        if age_max is not None:
            wheres.append(f"({age_expr}) <= {int(age_max)}")

    if not wheres:
        return None

    where_clause = " AND ".join(wheres)
    cte_name = next_cte_name("demo")
    cte_sql = (
        f"{cte_name} AS (\n"
        f"  SELECT p.person_id\n"
        f"  FROM {person_table} p\n"
        f"  WHERE {where_clause}\n"
        f")"
    )
    ctes.append(cte_sql)
    cte_names.append(cte_name)
    return cte_name


def build_cohort_dated_sql(
    criteria: dict, omop_schema: str = "omop_cdm",
) -> str:
    """
    Build SQL returning (person_id, cohort_start_date, cohort_end_date).

    Uses exit_criteria if present in the criteria JSON, otherwise defaults
    to end_of_observation.
    """
    _validate_identifier(omop_schema)
    base_sql = build_cohort_sql(criteria, omop_schema)

    # Determine date column from first inclusion criterion
    inclusion = criteria.get("inclusion", {})
    inc_criteria = inclusion.get("criteria", [])
    date_col = None
    domain_table = None
    for c in inc_criteria:
        domain = c.get("domain", "")
        if domain in _DOMAIN_TABLE_MAP:
            dmeta = _DOMAIN_TABLE_MAP[domain]
            date_col = dmeta["date_col"]
            domain_table = dmeta["table"]
            break

    if not date_col:
        return (
            f"SELECT p.person_id,\n"
            f"       op.observation_period_start_date AS cohort_start_date,\n"
            f"       op.observation_period_end_date AS cohort_end_date\n"
            f"FROM ({base_sql}) p\n"
            f"JOIN {omop_schema}.observation_period op ON p.person_id = op.person_id"
        )

    exit_criteria = criteria.get("exit_criteria")
    exit_type = exit_criteria.get("type", "end_of_observation") if exit_criteria else "end_of_observation"

    if exit_type == "fixed_duration" and exit_criteria:
        duration_days = int(exit_criteria.get("duration_days", 365))
        end_expr = (
            f"LEAST(op.observation_period_end_date, "
            f"MIN(t.{date_col}) + INTERVAL '{duration_days} days')"
        )
    elif exit_type == "event_based" and exit_criteria and exit_criteria.get("exit_event"):
        exit_event = exit_criteria["exit_event"]
        exit_event_criteria = {"inclusion": exit_event}
        exit_sql = build_cohort_sql(exit_event_criteria, omop_schema)
        exit_domain = exit_event.get("criteria", [{}])[0].get("domain", "")
        exit_date_col = None
        exit_table = None
        if exit_domain in _DOMAIN_TABLE_MAP:
            exit_dmeta = _DOMAIN_TABLE_MAP[exit_domain]
            exit_date_col = exit_dmeta["date_col"]
            exit_table = exit_dmeta["table"]

        if exit_date_col and exit_table:
            return (
                f"WITH cohort_base AS ({base_sql}),\n"
                f"cohort_start AS (\n"
                f"  SELECT cb.person_id, MIN(t.{date_col}) AS cohort_start_date\n"
                f"  FROM cohort_base cb\n"
                f"  JOIN {omop_schema}.{domain_table} t ON cb.person_id = t.person_id\n"
                f"  GROUP BY cb.person_id\n"
                f"),\n"
                f"exit_events AS (\n"
                f"  SELECT ep.person_id, MIN(et.{exit_date_col}) AS exit_date\n"
                f"  FROM ({exit_sql}) ep\n"
                f"  JOIN {omop_schema}.{exit_table} et ON ep.person_id = et.person_id\n"
                f"  GROUP BY ep.person_id\n"
                f")\n"
                f"SELECT cs.person_id,\n"
                f"       cs.cohort_start_date,\n"
                f"       COALESCE(\n"
                f"         CASE WHEN ee.exit_date > cs.cohort_start_date THEN ee.exit_date END,\n"
                f"         op.observation_period_end_date\n"
                f"       ) AS cohort_end_date\n"
                f"FROM cohort_start cs\n"
                f"JOIN {omop_schema}.observation_period op\n"
                f"  ON cs.person_id = op.person_id\n"
                f"  AND cs.cohort_start_date BETWEEN op.observation_period_start_date AND op.observation_period_end_date\n"
                f"LEFT JOIN exit_events ee ON cs.person_id = ee.person_id"
            )
        end_expr = "op.observation_period_end_date"
    else:
        end_expr = "op.observation_period_end_date"

    return (
        f"SELECT cb.person_id,\n"
        f"       MIN(t.{date_col}) AS cohort_start_date,\n"
        f"       {end_expr} AS cohort_end_date\n"
        f"FROM ({base_sql}) cb\n"
        f"JOIN {omop_schema}.{domain_table} t ON cb.person_id = t.person_id\n"
        f"JOIN {omop_schema}.observation_period op\n"
        f"  ON cb.person_id = op.person_id\n"
        f"GROUP BY cb.person_id, op.observation_period_end_date"
    )


def _criterion_label(criterion: dict) -> str:
    """Generate a human-readable label for a criterion (used in attrition)."""
    domain = criterion.get("domain", "?")
    concepts = criterion.get("concepts", [])
    if concepts:
        return f"{domain} ({len(concepts)} concepts)"
    return domain
