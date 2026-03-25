"""
ETL Lineage parser — extracts lineage graph from HTML ETL documentation.

Adapted from scripts/parse_etl_lineage.py for backend use.
Supports parsing EDS-style HTML docs that describe source→staging→OMOP flows.
"""
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTML section splitting
# ---------------------------------------------------------------------------

def split_repertoires(html: str) -> dict[str, str]:
    """Split the full HTML into named repertoire sections."""
    pattern = r"<h1[^>]*>\d+/\d+\)\s+Repertoire\s+'(\w+)'</h1>"
    matches = list(re.finditer(pattern, html))
    sections = {}
    for i, m in enumerate(matches):
        name = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(html)
        sections[name] = html[start:end]
    return sections


def _resolve_parent_source(file_name: str, dest_table: str) -> str:
    """Resolve source table from file name when source is 'class Parent'."""
    if not file_name:
        return dest_table
    parts = file_name.replace(".java", "").split(".")
    if len(parts) >= 2:
        schema = parts[0]
        name = parts[1]
        if "_to_" in name:
            src_part = name.split("_to_")[0]
            src_part = re.sub(r"^_?\d+_", "", src_part)
            return f"{schema}.{src_part}"
    return dest_table


def _resolve_java_class(name: str, file_name: str) -> str:
    """Resolve Java class syntax like \"class 'biology_axi' extends 'BiologyBase'\"
    to proper table names like 'cdm_source.biology_axi'."""
    m = re.match(r"class\s+'(\w+)'\s+extends\s+'(\w+)'", name)
    if m:
        class_name = m.group(1)
        if file_name and '.' in file_name:
            schema = file_name.split('.')[0]
            return f"{schema}.{class_name}"
        return class_name
    return name


def parse_transformation_block(block_html: str) -> dict:
    """Parse a single <h2>...<h2> transformation block."""
    result = {}

    h2_match = re.search(r"<h2[^>]*>\d+/\d+\)\s+Fichier\s+'([^']+)'</h2>", block_html)
    if h2_match:
        result["file"] = h2_match.group(1)

    h4_desc = re.search(r"<h4>((?:(?!</h4>).)+)</h4>", block_html)
    if h4_desc:
        desc = re.sub(r"<[^>]+>", "", h4_desc.group(1)).strip()
        if desc and desc not in ("Destination Indexes", "Source", "SQL", "Transformations"):
            result["description"] = desc

    # Source and destination from table header
    header_match = re.search(
        r"<th><em>Source</em><br/>(.*?)</th>\s*<th><em>Destination</em><br/>(.*?)</th>",
        block_html, re.DOTALL
    )
    if header_match:
        raw_source = re.sub(r"<[^>]+>", "", header_match.group(1)).strip()
        raw_dest = re.sub(r"<[^>]+>", "", header_match.group(2)).strip()

        if raw_source == "class Parent" or not raw_source:
            raw_source = _resolve_parent_source(result.get("file", ""), raw_dest)

        raw_source = _resolve_java_class(raw_source, result.get("file", ""))
        raw_dest = _resolve_java_class(raw_dest, result.get("file", ""))

        result["source_table"] = raw_source
        result["dest_table"] = raw_dest

    # Column mappings from table body
    columns = []
    rows = re.findall(r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>",
                       block_html, re.DOTALL)
    for src_raw, dst_raw, comment_raw in rows:
        src_col = re.sub(r"<[^>]+>", "", src_raw).strip()
        dst_text = re.sub(r"<[^>]+>", "", dst_raw).strip()
        comment = re.sub(r"<[^>]+>", "", comment_raw).strip()

        dst_col = dst_text
        col_type = ""
        type_match = re.match(r"(\S+)\s*\((\w[\w\s,]*)\)", dst_text)
        if type_match:
            dst_col = type_match.group(1)
            col_type = type_match.group(2).strip()

        col_entry: dict = {"source": src_col, "destination": dst_col}
        if col_type:
            col_entry["type"] = col_type
        if comment:
            col_entry["comment"] = comment
        columns.append(col_entry)

    if columns:
        result["columns"] = columns

    # SQL block
    sql_match = re.search(r"<h4>SQL</h4>\s*<pre>(.*?)</pre>", block_html, re.DOTALL)
    if sql_match:
        sql = sql_match.group(1).strip()
        sql = re.sub(r"<[^>]+>", "", sql)
        if sql:
            result["sql"] = sql

    # Transformation code
    trans_match = re.search(r"<h4>Transformations</h4>\s*<pre>(.*?)</pre>", block_html, re.DOTALL)
    if trans_match:
        code = trans_match.group(1).strip()
        code = re.sub(r"<[^>]+>", "", code)
        if code:
            result["transformation_code"] = code

    # WHERE clause
    where_match = re.search(r"<h4>Clause WHERE</h4>\s*<pre>(.*?)</pre>", block_html, re.DOTALL)
    if where_match:
        w = where_match.group(1).strip()
        w = re.sub(r"<[^>]+>", "", w)
        if w:
            result["where_filter"] = w

    # Primary key
    pk_section = re.search(r"<h5>Clé primaire:\s*'([^']*)'</h5>", block_html)
    if pk_section:
        result["source_primary_key"] = pk_section.group(1)

    return result


def split_transformations(section_html: str) -> list:
    """Split a repertoire section into individual transformation blocks."""
    parts = re.split(r'(?=<h2[^>]*>\d+/\d+\))', section_html)
    return [p for p in parts if re.match(r'\s*<h2', p.strip())]


# ---------------------------------------------------------------------------
# Layer classification
# ---------------------------------------------------------------------------

LAYER_MAP = {
    "axigate": "source",
    "axigate_theriaque": "source",
    "cora": "source",
    "pharma": "source",
    "pharma_archives": "source",
    "cdm_source": "staging",
    "omop_cdm": "omop",
    "structure": "reference",
}

SOURCE_SYSTEMS = {
    "axigate": {"name": "Axigate", "type": "Oracle",
                "description": "DPI - identites, sejours, mouvements, transmissions, constantes"},
    "axigate_theriaque": {"name": "Axigate Theriaque", "type": "Oracle",
                          "description": "Referentiel medicaments (Theriaque)"},
    "cora": {"name": "CORA", "type": "SQL Server",
             "description": "Diagnostics CIM-10, actes CCAM, biologie"},
    "pharma": {"name": "Pharma", "type": "Oracle",
               "description": "Prescriptions, dispensations, dispositifs medicaux"},
    "pharma_archives": {"name": "Pharma Archives", "type": "Oracle",
                        "description": "Archives prescriptions"},
}


def _infer_layer(table_name: str, fallback_rep: str) -> str:
    if "." in table_name:
        schema = table_name.split(".")[0]
        for prefix, layer in LAYER_MAP.items():
            if schema == prefix or schema.startswith(prefix):
                return layer
    return LAYER_MAP.get(fallback_rep, "unknown")


def _infer_system(table_name: str) -> str:
    if "." in table_name:
        schema = table_name.split(".")[0]
        for sys_key in SOURCE_SYSTEMS:
            if schema == sys_key or schema.startswith(sys_key):
                return sys_key
    return "unknown"


# ---------------------------------------------------------------------------
# Build lineage graph
# ---------------------------------------------------------------------------

def _add_inheritance_edges(edges: list, nodes: dict):
    """Add implicit edges for Java class inheritance patterns."""
    inheritance_map = {
        "cdm_source.biology_axi": "cdm_source.biology",
        "cdm_source.biology_cora": "cdm_source.biology",
    }
    existing_edges = {(e["source"], e["target"]) for e in edges}
    for child, parent in inheritance_map.items():
        if (child, parent) not in existing_edges and child in nodes:
            if parent not in nodes:
                nodes[parent] = {"table": parent, "layer": "staging", "system": "cdm_source"}
            edges.append({
                "source": child, "target": parent,
                "transformation_file": "",
                "description": f"Java inheritance: {child.split('.')[-1]} extends BiologyBase",
                "layer": "staging", "column_mappings": [],
            })


REAL_OMOP_TABLES = {
    "person", "visit_occurrence", "condition_occurrence", "measurement",
    "observation", "drug_exposure", "device_exposure", "procedure_occurrence",
    "cdm_source", "observation_period", "visit_detail", "death", "note",
    "specimen", "payer_plan_period", "cost", "drug_era", "condition_era",
}


def _resolve_omop_intermediates(edges: list, nodes: dict):
    """Fix intermediate omop_cdm nodes that are actually staging tables.

    The omop_cdm repertoire transforms e.g. omop_cdm.axi_patient → omop_cdm.person.
    But omop_cdm.axi_patient is really cdm_source.axi_patient (a staging table).
    This function:
    1. Rewrites edge sources from omop_cdm.X to cdm_source.X where applicable
    2. Adds bridging edges cdm_source.X → omop_cdm.X (now just cdm_source.X)
    3. Removes orphaned intermediate nodes
    """
    # Identify intermediate omop_cdm nodes (not real OMOP tables)
    intermediates = {}
    for name in list(nodes.keys()):
        if not name.startswith("omop_cdm."):
            continue
        short = name.split(".")[-1]
        if short in REAL_OMOP_TABLES:
            continue
        cdm_equiv = f"cdm_source.{short}"
        if cdm_equiv in nodes:
            intermediates[name] = cdm_equiv

    if not intermediates:
        return

    # Rewrite edge sources: omop_cdm.X → cdm_source.X
    for edge in edges:
        if edge["source"] in intermediates:
            edge["source"] = intermediates[edge["source"]]

    # Remove orphaned intermediate nodes (no longer referenced by any edge)
    referenced = set()
    for e in edges:
        referenced.add(e["source"])
        referenced.add(e["target"])
    for omop_name in intermediates:
        if omop_name not in referenced:
            nodes.pop(omop_name, None)


def _build_omop_chains(edges: list, nodes: dict) -> dict:
    """Build full upstream chains for each OMOP table."""
    by_target: dict[str, list] = {}
    for e in edges:
        by_target.setdefault(e["target"], []).append(e)

    def _trace(table: str, visited: set | None = None) -> list:
        if visited is None:
            visited = set()
        if table in visited:
            return []
        visited.add(table)
        chain = []
        for e in by_target.get(table, []):
            src = e["source"]
            entry = {
                "from": src, "to": table,
                "file": e.get("transformation_file", ""),
                "description": e.get("description", ""),
                "columns_count": len(e.get("column_mappings", [])),
            }
            upstream = _trace(src, visited.copy())
            if upstream:
                entry["upstream"] = upstream
            chain.append(entry)
        return chain

    omop_tables = [name for name, info in nodes.items() if info.get("layer") == "omop"]
    return {t: _trace(t) for t in sorted(omop_tables)}


def build_lineage(html_path: str) -> dict:
    """Parse the full ETL doc and build a lineage graph."""
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    date_match = re.search(r"<h2>Documentation générée le (.+?)</h2>", html)
    doc_date = date_match.group(1) if date_match else "unknown"

    author_match = re.search(r"<h3>(.*?)</h3>", html)
    author = re.sub(r"<[^>]+>", "", author_match.group(1)).strip() if author_match else "unknown"

    repertoires = split_repertoires(html)

    nodes: dict = {}
    edges: list = []

    for rep_name, rep_html in repertoires.items():
        layer = LAYER_MAP.get(rep_name, "unknown")
        blocks = split_transformations(rep_html)

        for block in blocks:
            t = parse_transformation_block(block)
            if not t:
                continue

            t["repertoire"] = rep_name
            t["layer"] = layer

            if t.get("source_table"):
                src_key = t["source_table"]
                if src_key not in nodes:
                    nodes[src_key] = {
                        "table": src_key,
                        "layer": _infer_layer(src_key, rep_name),
                        "system": _infer_system(src_key),
                    }

            if t.get("dest_table"):
                dst_key = t["dest_table"]
                if dst_key not in nodes:
                    nodes[dst_key] = {
                        "table": dst_key, "layer": layer, "system": rep_name,
                    }

                # Create edge (skip self-loops)
                if t.get("source_table") and t["source_table"] != dst_key:
                    edge: dict = {
                        "source": t["source_table"],
                        "target": t["dest_table"],
                        "transformation_file": t.get("file", ""),
                        "description": t.get("description", ""),
                        "layer": layer,
                        "column_mappings": t.get("columns", []),
                    }
                    if t.get("sql"):
                        edge["sql"] = t["sql"]
                    if t.get("transformation_code"):
                        edge["transformation_code"] = t["transformation_code"]
                    if t.get("where_filter"):
                        edge["where_filter"] = t["where_filter"]
                    edges.append(edge)

    _add_inheritance_edges(edges, nodes)
    _resolve_omop_intermediates(edges, nodes)
    omop_chains = _build_omop_chains(edges, nodes)

    return {
        "metadata": {
            "doc_date": doc_date,
            "author": author,
            "source_file": str(html_path),
            "total_nodes": len(nodes),
            "total_edges": len(edges),
        },
        "source_systems": SOURCE_SYSTEMS,
        "nodes": nodes,
        "edges": edges,
        "omop_chains": omop_chains,
    }
