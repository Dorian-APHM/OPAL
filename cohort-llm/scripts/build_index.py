"""
Embed CCAM_FR + CIM10_FR with multilingual-e5-base and save the index.

Plain version: each entry embedded with its bare label, no hierarchy enrichment.
(Numeric CIM10 meta-entries — chapter/block headers like '001', '002' — are
filtered out since they are not real disease codes.)

Output: index/embeddings.npy + index/metadata.jsonl
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
INDEX = ROOT / "index"
INDEX.mkdir(exist_ok=True)

MODEL_NAME = "intfloat/multilingual-e5-base"
BATCH_SIZE = 64

SOURCES = [
    {"file": "cim10_fr.csv",          "name": "CIM10_FR",         "domain": "Condition"},
    {"file": "ccam_fr.csv",           "name": "CCAM_FR",          "domain": "Procedure"},
    {"file": "drugs_aphm.csv",        "name": "DRUGS_APHM",       "domain": "Drug"},
    {"file": "measurements_aphm.csv", "name": "MEASUREMENTS_APHM","domain": "Measurement"},
]


def load_rows() -> list[dict]:
    rows = []
    for src in SOURCES:
        df = pd.read_csv(DATA / src["file"], dtype=str).fillna("")
        n_total = len(df)
        n_kept = 0
        for _, r in df.iterrows():
            code = str(r["code"]).strip()
            label = str(r["label"]).strip()
            # Skip CIM10 numeric meta-entries (chapter/block headers)
            if code.isdigit():
                continue
            rows.append({
                "source": src["name"],
                "domain": src["domain"],
                "code": code,
                "label": label,
            })
            n_kept += 1
        print(f"  {src['name']:10s} ({src['domain']:10s}) : {n_kept} kept / {n_total} in file")
    return rows


def main() -> None:
    print("Loading sources...")
    rows = load_rows()
    print(f"Total indexable entries: {len(rows)}\n")

    print(f"Loading model {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME, device="cuda")
    print(f"Device: {model.device}, dim: {model.get_sentence_embedding_dimension()}")

    passages = [f"passage: {r['label']}" for r in rows]
    print(f"\nEmbedding {len(passages)} entries (batch_size={BATCH_SIZE})...")
    t0 = time.time()
    emb = model.encode(
        passages,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype("float32")
    dt = time.time() - t0
    print(f"Done in {dt:.1f}s ({len(passages)/dt:.0f} entries/s)")
    print(f"Shape: {emb.shape}, size: {emb.nbytes/1e6:.1f} MB")

    np.save(INDEX / "embeddings.npy", emb)
    with open(INDEX / "metadata.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nSaved {INDEX/'embeddings.npy'} and metadata.jsonl")


if __name__ == "__main__":
    main()
