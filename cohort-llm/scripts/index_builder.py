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


def _resolve_db_url() -> str:
    url = DB_URL
    if "{pw}" in url:
        pw = os.environ.get("POSTGRES_PASSWORD", "")
        url = url.format(pw=pw)
    return url


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
            rows.append({
                "domain": r["domain"],
                "source_value": (r["source_value"] or "").strip(),
                "source_atc": (r["source_atc"] or "").strip(),
                "label": label,
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
    # the runner returns L2-normalized vectors, so cosine == dot product.
    labels = [r["label"] for r in rows]
    t0 = time.time()
    emb = client.encode(labels).astype("float32")
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
