"""
Cohort Pathways Analysis Engine — ATLAS-style treatment pathway computation.

Implements the methodology from Hripcsak et al. (2016, PNAS) as generalized
in OHDSI ATLAS "Cohort Pathways":

1. For each person in the **target cohort**, find all overlapping events from
   one or more **event cohorts** (user-defined concept sets).
2. Collapse temporally adjacent/overlapping eras of the same event into
   contiguous eras (with a configurable gap merge window).
3. Record the ordered sequence of event eras (treatment pathway) per person.
4. Aggregate identical sequences and produce counts + percentages.

The output is a hierarchical tree suitable for sunburst visualisation,
plus a flat table of the top-N distinct pathways.
"""
import logging
from collections import Counter, defaultdict
from typing import Any

from config import DOMAIN_CONFIG
from modules.cohort.sql_builder import build_cohort_sql
from utils.sql_safety import safe_identifier

logger = logging.getLogger(__name__)

# Maximum pathway depth (rings in the sunburst)
_MAX_DEPTH = 5
_DEFAULT_MIN_CELL_COUNT = 5
_DEFAULT_COMBO_WINDOW = 0


def run_pathways_analysis(
    conn,
    criteria: dict,
    event_cohorts: list[dict],
    omop_schema: str,
    *,
    max_depth: int = _MAX_DEPTH,
    min_cell_count: int = _DEFAULT_MIN_CELL_COUNT,
    combo_window: int = _DEFAULT_COMBO_WINDOW,
    progress_callback=None,
) -> dict[str, Any]:
    """
    Run a pathways analysis for a target cohort.

    Parameters
    ----------
    conn : psycopg2 connection
        Open connection to the OMOP CDM.
    criteria : dict
        Target cohort criteria JSON (same format as cohort builder).
    event_cohorts : list[dict]
        Each dict has:
          - name (str): Display label (e.g. "ACE Inhibitors")
          - domain (str): OMOP domain (e.g. "Drug", "Condition")
          - concept_ids (list[int]): Concept IDs defining the event
          - include_descendants (bool, optional): Expand via concept_ancestor
    omop_schema : str
        Schema name for OMOP tables.
    max_depth : int
        Maximum number of pathway steps to track.
    min_cell_count : int
        Suppress pathways with fewer than this many persons.
    combo_window : int
        Days within which overlapping events are merged into a "combo" era.
    progress_callback : callable, optional
        Called as progress_callback(completed, total, label).

    Returns
    -------
    dict with keys:
      - target_size (int): persons in target cohort
      - persons_with_pathways (int): persons with ≥1 event
      - pathways_table (list[dict]): top distinct pathways with counts
      - sunburst_tree (dict): hierarchical tree for sunburst viz
      - event_colors (dict): name → colour assignment
    """
    from modules.cohort.sql_builder import _smap
    omop_schema = _smap(omop_schema)
    safe_identifier(omop_schema)
    dialect = conn.dialect
    omop_schema._dialect = dialect

    def _analyze(cur, name):
        sql = dialect.analyze_table(name)
        if sql:
            cur.execute(sql)

    total_steps = 3 + len(event_cohorts)
    completed = [0]

    def _report(label: str):
        completed[0] += 1
        if progress_callback:
            progress_callback(completed[0], total_steps, label)

    with dialect.dict_cursor(conn) as cur:
        # ── Step 1: Materialise target cohort with observation period ──
        cohort_sql = build_cohort_sql(criteria, omop_schema)
        cur.execute(dialect.drop_table_if_exists("opal_pw_target"))
        cur.execute(dialect.create_temp_table_as("opal_pw_target", f"""
            SELECT DISTINCT p.person_id,
                   op.observation_period_start_date AS cohort_start,
                   op.observation_period_end_date   AS cohort_end
            FROM ({cohort_sql}) p
            JOIN {omop_schema.t('observation_period')} op
              ON p.person_id = op.person_id
        """))
        cur.execute(dialect.create_index("opal_pw_target", "person_id"))
        _analyze(cur, "opal_pw_target")
        cur.execute("SELECT COUNT(DISTINCT person_id) AS n FROM opal_pw_target")
        target_size = cur.fetchone()["n"]
        _report("Target cohort materialised")

        # ── Step 2: For each event cohort, collect raw events ──
        cur.execute(dialect.drop_table_if_exists("opal_pw_events"))
        cur.execute(dialect.create_temp_table(
            "opal_pw_events",
            f"person_id {dialect.big_int_type()}, event_name VARCHAR(255), event_start DATE, event_end DATE",
        ))

        for ec in event_cohorts:
            name = ec["name"]
            domain = ec["domain"]
            concept_ids = ec.get("concept_ids", [])
            source_codes = ec.get("source_codes", [])
            include_desc = ec.get("include_descendants", False)

            cfg = DOMAIN_CONFIG.get(domain)
            if not cfg:
                _report(f"Skipped {name}")
                continue

            # Validate concept_ids: must be positive integers
            validated_ids = []
            for cid in concept_ids:
                cid_int = int(cid)
                if cid_int <= 0:
                    continue
                validated_ids.append(cid_int)

            if not validated_ids and not source_codes:
                _report(f"Skipped {name} (no concept_ids or source_codes)")
                continue

            table = cfg["table"]
            cid_col = cfg["concept_id"]
            date_col = cfg["date_col"]
            source_value_col = cfg.get("source_value")
            source_name_col = cfg.get("source_name")
            # End date column (if available)
            end_date_map = {
                "Condition": "condition_end_date",
                "Drug": "drug_exposure_end_date",
                "Visit": "visit_end_date",
                "Device": "device_exposure_end_date",
            }
            end_col = end_date_map.get(domain)
            end_expr = f"COALESCE(t.{end_col}, t.{date_col})" if end_col else f"t.{date_col}"

            # Build concept filter
            concept_filter = None
            if validated_ids:
                ids_str = ",".join(str(cid) for cid in validated_ids)
                if include_desc:
                    # Explicit ids OR their descendants (engine-neutral; avoids unnest/ARRAY).
                    concept_filter = (
                        f"(t.{cid_col} IN ({ids_str})"
                        f" OR t.{cid_col} IN ("
                        f"   SELECT descendant_concept_id FROM {omop_schema.t('concept_ancestor')}"
                        f"   WHERE ancestor_concept_id IN ({ids_str})))"
                    )
                else:
                    concept_filter = f"t.{cid_col} IN ({ids_str})"

            # Build source code filter (parameterised — no engine-specific literal quoting)
            source_filter = None
            event_params: dict = {"ename": name}
            if source_codes and source_value_col:
                sc_keys = []
                for i, code in enumerate(source_codes):
                    k = f"sc{i}"
                    event_params[k] = str(code)
                    sc_keys.append(f"%({k})s")
                placeholders = ", ".join(sc_keys)
                source_parts = [f"t.{source_value_col} IN ({placeholders})"]
                if source_name_col:
                    source_parts.append(f"t.{source_name_col} IN ({placeholders})")
                source_filter = f"({' OR '.join(source_parts)})"

            # Combine filters with OR
            if concept_filter and source_filter:
                where_filter = f"({concept_filter} OR {source_filter})"
            elif concept_filter:
                where_filter = concept_filter
            elif source_filter:
                where_filter = source_filter
            else:
                _report(f"Skipped {name} (no valid filters)")
                continue

            dialect.execute(cur, f"""
                INSERT INTO opal_pw_events (person_id, event_name, event_start, event_end)
                SELECT tgt.person_id,
                       %(ename)s,
                       t.{date_col},
                       {end_expr}
                FROM opal_pw_target tgt
                JOIN {omop_schema.t(table)} t
                  ON tgt.person_id = t.person_id
                 AND t.{date_col} BETWEEN tgt.cohort_start AND tgt.cohort_end
                WHERE {where_filter}
            """, event_params)
            _report(f"Events: {name}")

        cur.execute(dialect.create_index("opal_pw_events", "person_id, event_start"))
        _analyze(cur, "opal_pw_events")

        # ── Step 3: Build eras (collapse overlapping events of same name) ──
        # Using a gap-merge approach: events of the same type within
        # combo_window days are merged into one continuous era.
        cur.execute(dialect.drop_table_if_exists("opal_pw_eras"))
        cur.execute(dialect.create_temp_table_as("opal_pw_eras", f"""
            WITH ordered AS (
                SELECT person_id, event_name, event_start, event_end,
                       LAG(event_end) OVER (
                           PARTITION BY person_id, event_name
                           ORDER BY event_start
                       ) AS prev_end
                FROM opal_pw_events
            ),
            groups AS (
                SELECT ordered.*,
                       SUM(CASE
                           WHEN prev_end IS NULL
                             OR event_start > {dialect.date_add('prev_end', int(combo_window))}
                           THEN 1 ELSE 0
                       END) OVER (
                           PARTITION BY person_id, event_name
                           ORDER BY event_start
                       ) AS era_group
                FROM ordered
            )
            SELECT person_id,
                   event_name,
                   MIN(event_start) AS era_start,
                   MAX(event_end)   AS era_end
            FROM groups
            GROUP BY person_id, event_name, era_group
        """))
        cur.execute(dialect.create_index("opal_pw_eras", "person_id, era_start"))
        _analyze(cur, "opal_pw_eras")
        _report("Eras collapsed")

        # ── Step 4: Build per-person pathway sequences ──
        # For each person, order eras by era_start and record the sequence
        # of event_name values (limited to max_depth steps).
        # Concurrent events (same era_start day) are combined as "A+B".
        cur.execute(f"""
            WITH ranked AS (
                SELECT person_id, era_start, event_name,
                       DENSE_RANK() OVER (
                           PARTITION BY person_id ORDER BY era_start
                       ) AS step_rank
                FROM opal_pw_eras
            ),
            steps AS (
                SELECT person_id, step_rank,
                       {dialect.string_agg('event_name', '+', order_by='event_name')} AS step_label
                FROM ranked
                WHERE step_rank <= {int(max_depth)}
                GROUP BY person_id, step_rank
            )
            SELECT person_id, step_rank, step_label
            FROM steps
            ORDER BY person_id, step_rank
        """)
        rows = cur.fetchall()

        # Clean up temp tables
        cur.execute(dialect.drop_table_if_exists("opal_pw_eras"))
        cur.execute(dialect.drop_table_if_exists("opal_pw_events"))
        cur.execute(dialect.drop_table_if_exists("opal_pw_target"))

    # ── Step 5: Aggregate pathways in Python ──
    # Build per-person pathway list
    person_paths: dict[int, list[str]] = defaultdict(list)
    for r in rows:
        person_paths[r["person_id"]].append(r["step_label"])

    persons_with_pathways = len(person_paths)

    # Count full pathway sequences
    pathway_counter: Counter = Counter()
    for pid, steps in person_paths.items():
        key = tuple(steps)
        pathway_counter[key] += 1

    # Build pathways table (top pathways)
    pathways_table = []
    for path, count in pathway_counter.most_common():
        if count < min_cell_count:
            continue
        pathways_table.append({
            "pathway": list(path),
            "count": count,
            "pct": round(100.0 * count / target_size, 2) if target_size else 0,
        })

    # ── Step 6: Build sunburst tree ──
    sunburst_tree = _build_sunburst_tree(person_paths, min_cell_count, target_size)

    # Assign colours to event names
    all_names = sorted({
        name
        for steps in person_paths.values()
        for step_label in steps
        for name in step_label.split("+")
    })
    palette = [
        "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
        "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
        "#AF7AA1", "#86BCB6", "#D37295", "#FABFD2", "#B6992D",
    ]
    event_colors = {
        name: palette[i % len(palette)]
        for i, name in enumerate(all_names)
    }

    _report("Analysis complete")

    return {
        "target_size": target_size,
        "persons_with_pathways": persons_with_pathways,
        "pathways_table": pathways_table,
        "sunburst_tree": sunburst_tree,
        "event_colors": event_colors,
    }


def _build_sunburst_tree(
    person_paths: dict[int, list[str]],
    min_cell_count: int,
    target_size: int,
) -> dict:
    """
    Build a hierarchical tree for sunburst visualisation.

    Each node: { name, count, pct, children: [...] }
    The root represents the full target cohort.
    Each ring level represents step N in the pathway.
    """
    root: dict[str, Any] = {
        "name": "Target",
        "count": target_size,
        "pct": 100.0,
        "children": [],
    }

    # Recursively build tree by counting persons at each step prefix
    def _add_person_to_tree(node: dict, steps: list[str], depth: int):
        if depth >= len(steps):
            return
        step_name = steps[depth]
        # Find or create child
        child = None
        for c in node["children"]:
            if c["name"] == step_name:
                child = c
                break
        if child is None:
            child = {"name": step_name, "count": 0, "pct": 0.0, "children": []}
            node["children"].append(child)
        child["count"] += 1
        _add_person_to_tree(child, steps, depth + 1)

    for pid, steps in person_paths.items():
        _add_person_to_tree(root, steps, 0)

    # Prune nodes below min_cell_count and compute percentages
    _prune_and_compute_pct(root, target_size, min_cell_count)

    return root


def _prune_and_compute_pct(node: dict, total: int, min_count: int):
    """Recursively prune small nodes and compute percentages."""
    node["pct"] = round(100.0 * node["count"] / total, 2) if total else 0.0
    node["children"] = [c for c in node["children"] if c["count"] >= min_count]
    # Sort children by count descending
    node["children"].sort(key=lambda c: c["count"], reverse=True)
    for child in node["children"]:
        _prune_and_compute_pct(child, total, min_count)
