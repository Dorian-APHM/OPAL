"""
Build the retrieval index from OPAL's source_value_cache (opal-db), per CDM.

No CSV files: the vocabulary (Condition, Procedure, Drug, Measurement) is read
straight from OPAL's app DB. The cache is already enriched with the reference
nomenclatures (CIM10/CCAM) when OPAL populates it, so it IS the source of truth
and reflects exactly the codes present in the active CDM.

Index is cached per CDM under INDEX_CACHE/<cdm_name>/.
"""
import json
import os
import re
import time
from pathlib import Path

import numpy as np
import psycopg2
import psycopg2.extras

from embed_client import EmbeddingClient, EMBED_MODEL_TAG

# Embeddings come from the shared opal-sapbert runner (see embed_client). MODEL_NAME
# tags each built index so a stale one (model swap, or a previous e5 build) is rebuilt.
MODEL_NAME = EMBED_MODEL_TAG
BATCH_SIZE = 64
_DEFAULT_CACHE = Path(__file__).resolve().parent.parent / "index_cache"
INDEX_CACHE = Path(os.environ.get("COHORT_LLM_INDEX_CACHE", str(_DEFAULT_CACHE)))

# In-container the DB is reachable as opal-db:5432; for local dev, host port 5434.
DB_URL = os.environ.get(
    "COHORT_LLM_DB_URL",
    "postgresql://opal:{pw}@localhost:5434/opal",
)

# Domains we index from the cache, in OPAL's source_value_cache vocabulary.
DOMAINS = ["Condition", "Procedure", "Drug", "Measurement"]

_PUNCT_ONLY = re.compile(r"^[\W_]+$")

# ── Drug label cleaning ────────────────────────────────────────────────
# CDM drug labels are "MOLECULE DOSE FORME (MARQUE)" — the dose/form noise DILUTES
# the molecule in SapBERT's embedding so much that even an exact INN scores ~0.44
# ("METFORMINE 500 MG CPR (GLUCOPHAGE)" vs "metformine" = 0.44, vs cleaned = 0.62+).
# We strip dose/units/galenic-form but KEEP molecule AND brand together (both are
# searched: "metformine" and "glucophage"). Only the EMBEDDED text is cleaned; the
# original label is kept for display.
_DIGIT_TOKEN = re.compile(r"\S*\d\S*")                       # 500MG, 1G, 100MG/4ML, B12…
_UNIT_WORD = re.compile(r"\b(?:MG|G|MCG|µG|UG|UI|MUI|KUI|ML|CL|L|MMOL|MEQ|µ|%)\b", re.I)
_FORM_WORD = re.compile(
    r"\b(?:CP|CPR|COMPRIMES?|GELULES?|G[EÉ]LULES?|GEL|CAPSULES?|SACHETS?|SUPPOS?|"
    r"SUPPOSITOIRES?|INJ(?:ECTABLE)?|IV|IM|SC|PERF|SOL(?:UTION)?|SUSP(?:ENSION)?|"
    r"BUV(?:ABLE)?|SIROP|PDR|POUDRE|POMMADE|CR[EÈ]ME|COLLYRE|PATCH|DISP(?:ERSIBLE)?|"
    r"L\.?P|LM|EFF(?:ERVESCENT)?|ORO(?:DISP)?|FLACON|FL|AMP(?:OULE)?|STYLO|DOSE|"
    r"TRANSD(?:ERMIQUE)?|INHAL?|NEBUL|GTT|GOUTTES?|POCHE|SERINGUE|SRG|TUBE|P[AÂ]TE|"
    r"EMULSION|EMPL[AÂ]TRE)\b",
    re.I,
)


def clean_drug_label(label: str) -> str:
    """Strip dose/units/galenic-form from a drug label, keep molecule + brand.

    Falls back to the lowercased original if cleaning would empty the string.
    """
    s = re.sub(r"[()]", " ", label)      # drop parens, keep their content
    s = _DIGIT_TOKEN.sub(" ", s)         # drop dosage tokens (anything with a digit)
    s = _UNIT_WORD.sub(" ", s)           # drop leftover standalone units (MG, G…)
    s = _FORM_WORD.sub(" ", s)           # drop galenic forms / routes
    s = re.sub(r"[/.,;:+]", " ", s)
    s = re.sub(r"\b\w\b", " ", s)        # drop single-char leftovers (A, C, V…)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s or label.strip().lower()


def _resolve_db_url() -> str:
    url = DB_URL
    if "{pw}" in url:
        pw = os.environ.get("POSTGRES_PASSWORD", "")
        url = url.format(pw=pw)
    return url


def load_atc_labels(cdm_name: str, conn=None) -> dict[str, str]:
    """Return {ATC code -> class name} for a CDM (app DB `atc_labels`), for display.

    Used by the retriever to title Drug concept-set groups with their ATC class name
    instead of a member's product label. Resilient: returns {} if the table is absent/
    empty (the retriever then falls back to the representative member label).
    """
    own = conn is None
    if own:
        conn = psycopg2.connect(_resolve_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT atc_code, label FROM atc_labels WHERE cdm_name = %s", (cdm_name,)
            )
            return {(c or "").strip().upper(): (n or "").strip() for c, n in cur.fetchall()}
    except Exception:
        return {}
    finally:
        if own:
            conn.close()


def fetch_cache_rows(cdm_name: str, conn) -> list[dict]:
    """Read source_value_cache rows for a CDM, all indexed domains, with clean labels."""
    rows: list[dict] = []
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT domain, source_value, source_name, source_atc, n_records
            FROM source_value_cache
            WHERE cdm_name = %s AND domain = ANY(%s)
              AND source_name IS NOT NULL
              AND length(trim(source_name)) >= 3
            ORDER BY domain, n_records DESC
            """,
            (cdm_name, DOMAINS),
        )
        for r in cur.fetchall():
            label = (r["source_name"] or "").strip()
            if _PUNCT_ONLY.match(label):       # drop punctuation-only labels
                continue
            # Drugs: embed a cleaned label (dose/form stripped) so molecule/brand
            # queries aren't diluted. Other domains embed the label as-is.
            embed_text = clean_drug_label(label) if r["domain"] == "Drug" else label
            rows.append({
                "domain": r["domain"],
                "source_value": (r["source_value"] or "").strip(),
                "source_atc": (r["source_atc"] or "").strip(),
                "label": label,
                "embed_text": embed_text,
                "n_records": int(r["n_records"] or 0),
            })
    return rows


def build_index_for_cdm(cdm_name: str, client: EmbeddingClient, conn) -> tuple[np.ndarray, list[dict]]:
    """Build + persist the index for one CDM. Returns (embeddings, metadata)."""
    rows = fetch_cache_rows(cdm_name, conn)
    if not rows:
        raise ValueError(f"No source_value_cache rows for CDM {cdm_name!r}")

    by_domain: dict[str, int] = {}
    for r in rows:
        by_domain[r["domain"]] = by_domain.get(r["domain"], 0) + 1
    print(f"[{cdm_name}] {len(rows)} entries: "
          + ", ".join(f"{d}={n}" for d, n in sorted(by_domain.items())))

    # SapBERT encodes raw entity names (no e5-style "passage:"/"query:" prefix);
    # the runner returns L2-normalized vectors, so cosine == dot product. Drug rows
    # carry a cleaned embed_text (dose/form stripped); others embed the label.
    texts = [r.get("embed_text") or r["label"] for r in rows]
    t0 = time.time()
    emb = client.encode(texts).astype("float32")
    print(f"[{cdm_name}] embedded {len(rows)} in {time.time()-t0:.1f}s, {emb.nbytes/1e6:.0f} MB")

    out = INDEX_CACHE / cdm_name
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "embeddings.npy", emb)
    with open(out / "metadata.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "model.txt").write_text(EMBED_MODEL_TAG, encoding="utf-8")  # index provenance
    return emb, rows


def load_cached(cdm_name: str) -> tuple[np.ndarray, list[dict]] | None:
    out = INDEX_CACHE / cdm_name
    emb_path, meta_path = out / "embeddings.npy", out / "metadata.jsonl"
    if not (emb_path.exists() and meta_path.exists()):
        return None
    # Reject an index built by a different model (e.g. a previous e5 build, which
    # has no model.txt): its vectors are incomparable with SapBERT queries.
    tag_path = out / "model.txt"
    tag = tag_path.read_text(encoding="utf-8").strip() if tag_path.exists() else None
    if tag != EMBED_MODEL_TAG:
        print(f"[{cdm_name}] cached index model={tag!r} != {EMBED_MODEL_TAG!r} — rebuilding")
        return None
    emb = np.load(emb_path)
    with open(meta_path, encoding="utf-8") as f:
        meta = [json.loads(line) for line in f]
    return emb, meta


def load_or_build(cdm_name: str, client: EmbeddingClient,
                  conn=None, force: bool = False) -> tuple[np.ndarray, list[dict]]:
    """Lazy: return cached index if present (unless force), else build from opal-db."""
    if not force:
        cached = load_cached(cdm_name)
        if cached is not None:
            print(f"[{cdm_name}] loaded cached index ({cached[0].shape[0]} entries)")
            return cached
    own_conn = conn is None
    if own_conn:
        conn = psycopg2.connect(_resolve_db_url())
    try:
        return build_index_for_cdm(cdm_name, client, conn)
    finally:
        if own_conn:
            conn.close()


# CLI: python index_builder.py <cdm_name> [--force]
if __name__ == "__main__":
    import sys
    cdm = sys.argv[1] if len(sys.argv) > 1 else "cdm_omop_20260314"
    force = "--force" in sys.argv
    print(f"Embeddings via opal-sapbert runner ({MODEL_NAME})...")
    client = EmbeddingClient()
    emb, meta = load_or_build(cdm, client, force=force)
    print(f"Done. Index: {emb.shape}, {len(meta)} entries.")
