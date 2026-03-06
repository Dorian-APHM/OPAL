"""
SapBERT-based semantic mapping: CCAM (EN) → SNOMED Procedure.

Connects to the OPAL app DB to retrieve:
  - CDM connection details (to extract SNOMED standard concepts)
  - CCAM source terms (from CSV file or reference_codebooks table)

Then uses SapBERT to compute embeddings and find the top-N SNOMED matches
for each CCAM source term.

Usage:
    pip install torch transformers numpy psycopg2-binary cryptography

    # From CSV file (recommended — uses real CCAM codes like QCJA003):
    python scripts/sapbert_mapping.py --cdm <cdm_name> --csv ccam_athena.csv [--top 5]

    # From OPAL reference_codebooks table:
    python scripts/sapbert_mapping.py --cdm <cdm_name> --ref CCAM_EN [--top 5]

Output CSV can be loaded into OPAL as a reference or used to batch-approve mappings.
"""
import argparse
import csv
import os
import sys
import time
from pathlib import Path

import numpy as np
import psycopg2
from psycopg2.extras import DictCursor

# ---------------------------------------------------------------------------
# OPAL app DB connection (same as backend config)
# ---------------------------------------------------------------------------
OPAL_DB_URL = os.getenv("OPAL_DATABASE_URL", "postgresql://opal:opal@localhost:5434/opal")

# Fernet key for CDM password decryption
SECRET_KEY_FILE = Path(__file__).parent.parent / "backend" / "data" / ".secret_key"


def decrypt_password(encrypted: str) -> str:
    """Decrypt a CDM password using OPAL's Fernet key."""
    from cryptography.fernet import Fernet
    if not encrypted:
        return ""
    with open(SECRET_KEY_FILE, "rb") as f:
        key = f.read()
    return Fernet(key).decrypt(encrypted.encode("utf-8")).decode("utf-8")


def get_opal_connection():
    """Connect to OPAL's internal PostgreSQL."""
    # Parse URL: postgresql://user:pass@host:port/dbname
    from urllib.parse import urlparse
    parsed = urlparse(OPAL_DB_URL)
    return psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        dbname=parsed.path.lstrip("/"),
        user=parsed.username,
        password=parsed.password,
    )


def get_cdm_info(opal_conn, cdm_name: str) -> dict:
    """Fetch CDM connection details from OPAL app DB."""
    with opal_conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute(
            "SELECT db_host, db_port, db_name, db_user, db_password_encrypted, omop_schema "
            "FROM cdm_configs WHERE name = %s",
            (cdm_name,),
        )
        row = cur.fetchone()
        if not row:
            print(f"ERROR: CDM '{cdm_name}' not found in OPAL database.")
            sys.exit(1)
        return {
            "host": row["db_host"],
            "port": row["db_port"],
            "dbname": row["db_name"],
            "user": row["db_user"],
            "password": decrypt_password(row["db_password_encrypted"]),
            "schema": row["omop_schema"],
        }


def get_ccam_from_csv(csv_path: str) -> list[dict]:
    """Read CCAM entries from a CSV file (code,description,...)."""
    entries = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get("code", "").strip()
            desc = row.get("description", "").strip()
            if code and desc:
                entries.append({"code": code, "description": desc})
    if not entries:
        print(f"ERROR: No entries found in CSV '{csv_path}'.")
        sys.exit(1)
    return entries


def get_ccam_en_entries(opal_conn, ref_name: str = "CCAM_EN") -> list[dict]:
    """Fetch CCAM_EN entries from reference_codebooks table."""
    with opal_conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute(
            "SELECT code, description FROM reference_codebooks WHERE name = %s ORDER BY code",
            (ref_name,),
        )
        rows = cur.fetchall()
        if not rows:
            print(f"ERROR: No entries found for reference '{ref_name}'. Load it first via OPAL mapping UI.")
            sys.exit(1)
        return [{"code": r["code"], "description": r["description"]} for r in rows]


def get_snomed_procedures(cdm_conn, schema: str) -> list[dict]:
    """Extract all valid standard Procedure concepts from the CDM vocabulary."""
    sql = f"""
        SELECT concept_id, concept_code, concept_name, vocabulary_id
        FROM {schema}.concept
        WHERE domain_id = 'Procedure'
          AND standard_concept = 'S'
          AND invalid_reason IS NULL
          AND concept_name IS NOT NULL
          AND concept_name != ''
          AND concept_name NOT ILIKE '%%(Deprecated)%%'
        ORDER BY concept_id
    """
    with cdm_conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return [
        {
            "concept_id": r["concept_id"],
            "concept_code": r["concept_code"],
            "concept_name": r["concept_name"],
            "vocabulary_id": r["vocabulary_id"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# SapBERT encoding
# ---------------------------------------------------------------------------
def load_sapbert(model_name: str = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"):
    """Load SapBERT model and tokenizer."""
    import torch
    from transformers import AutoTokenizer, AutoModel

    print(f"Loading SapBERT model: {model_name}")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)
    model.eval()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    print(f"  Device: {device}")
    return tokenizer, model, device


def encode_texts(tokenizer, model, device, texts: list[str], batch_size: int = 128) -> np.ndarray:
    """Encode a list of texts into SapBERT embeddings (CLS token)."""
    import torch

    all_embeddings = []
    total = len(texts)

    for i in range(0, total, batch_size):
        batch = texts[i : i + batch_size]
        inputs = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=64,
            return_tensors="pt",
        ).to(device)

        with torch.no_grad():
            outputs = model(**inputs)
            # CLS token embedding
            cls_embeddings = outputs.last_hidden_state[:, 0, :].cpu().numpy()
            all_embeddings.append(cls_embeddings)

        done = min(i + batch_size, total)
        if done % 1000 == 0 or done == total:
            print(f"  Encoded {done}/{total}")

    return np.vstack(all_embeddings)


def compute_topk(source_embs: np.ndarray, target_embs: np.ndarray, top_k: int = 5) -> np.ndarray:
    """
    Compute cosine similarity and return top-K indices + scores for each source.
    Returns shape (n_source, top_k) of indices and (n_source, top_k) of scores.
    """
    # L2 normalize
    source_norm = source_embs / np.linalg.norm(source_embs, axis=1, keepdims=True)
    target_norm = target_embs / np.linalg.norm(target_embs, axis=1, keepdims=True)

    n_source = source_norm.shape[0]
    chunk_size = 500  # process in chunks to limit memory
    all_indices = []
    all_scores = []

    for i in range(0, n_source, chunk_size):
        chunk = source_norm[i : i + chunk_size]
        # (chunk_size, n_target)
        sims = chunk @ target_norm.T
        # top-K per row
        top_idx = np.argsort(sims, axis=1)[:, -top_k:][:, ::-1]
        top_scores = np.take_along_axis(sims, top_idx, axis=1)
        all_indices.append(top_idx)
        all_scores.append(top_scores)

        done = min(i + chunk_size, n_source)
        if done % 1000 == 0 or done == n_source:
            print(f"  Similarity {done}/{n_source}")

    return np.vstack(all_indices), np.vstack(all_scores)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="SapBERT CCAM→SNOMED mapping")
    parser.add_argument("--cdm", required=True, help="CDM name registered in OPAL")
    parser.add_argument("--csv", default=None, help="CSV file with CCAM codes (code,description columns). Uses real CCAM codes.")
    parser.add_argument("--ref", default="CCAM_EN", help="Reference codebook name if --csv not provided (default: CCAM_EN)")
    parser.add_argument("--top", type=int, default=5, help="Top-K matches per source term")
    parser.add_argument("--output", default="sapbert_results.csv", help="Output CSV path")
    parser.add_argument("--model", default="cambridgeltl/SapBERT-from-PubMedBERT-fulltext", help="HuggingFace model")
    parser.add_argument("--batch-size", type=int, default=128, help="Encoding batch size")
    parser.add_argument("--save-embeddings", action="store_true", help="Save embeddings as .npy files")
    args = parser.parse_args()

    t0 = time.time()

    # --- Step 1: Connect and fetch data ---
    print("=" * 60)
    print("Step 1: Fetching data from databases")
    print("=" * 60)

    opal_conn = get_opal_connection()
    cdm_info = get_cdm_info(opal_conn, args.cdm)

    print(f"  CDM: {args.cdm} ({cdm_info['host']}:{cdm_info['port']}/{cdm_info['dbname']})")
    print(f"  Schema: {cdm_info['schema']}")

    # Fetch CCAM source terms
    if args.csv:
        ccam_entries = get_ccam_from_csv(args.csv)
        print(f"  CCAM from CSV '{args.csv}': {len(ccam_entries)} entries")
    else:
        ccam_entries = get_ccam_en_entries(opal_conn, args.ref)
        print(f"  {args.ref} from DB: {len(ccam_entries)} entries")
    opal_conn.close()

    # Fetch SNOMED Procedures
    cdm_conn = psycopg2.connect(
        host=cdm_info["host"],
        port=cdm_info["port"],
        dbname=cdm_info["dbname"],
        user=cdm_info["user"],
        password=cdm_info["password"],
    )
    snomed_concepts = get_snomed_procedures(cdm_conn, cdm_info["schema"])
    cdm_conn.close()
    print(f"  SNOMED Procedure concepts: {len(snomed_concepts)}")

    if not ccam_entries or not snomed_concepts:
        print("ERROR: No data to process.")
        sys.exit(1)

    # --- Step 2: Encode with SapBERT ---
    print()
    print("=" * 60)
    print("Step 2: Encoding with SapBERT")
    print("=" * 60)

    tokenizer, model, device = load_sapbert(args.model)

    ccam_texts = [e["description"] for e in ccam_entries]
    snomed_texts = [c["concept_name"] for c in snomed_concepts]

    print(f"\nEncoding {len(ccam_texts)} CCAM terms...")
    ccam_embs = encode_texts(tokenizer, model, device, ccam_texts, args.batch_size)

    print(f"\nEncoding {len(snomed_texts)} SNOMED terms...")
    snomed_embs = encode_texts(tokenizer, model, device, snomed_texts, args.batch_size)

    if args.save_embeddings:
        output_dir = Path(args.output).parent
        np.save(output_dir / "ccam_embeddings.npy", ccam_embs)
        np.save(output_dir / "snomed_procedure_embeddings.npy", snomed_embs)
        print(f"  Saved embeddings to {output_dir}/")

    # --- Step 3: Compute similarity ---
    print()
    print("=" * 60)
    print("Step 3: Computing cosine similarity (top-{})".format(args.top))
    print("=" * 60)

    top_indices, top_scores = compute_topk(ccam_embs, snomed_embs, args.top)

    # --- Step 4: Write CSV ---
    print()
    print("=" * 60)
    print("Step 4: Writing results")
    print("=" * 60)

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "source_code",
            "source_name",
            "rank",
            "target_concept_id",
            "target_concept_code",
            "target_concept_name",
            "target_vocabulary_id",
            "similarity",
        ])

        for i, ccam in enumerate(ccam_entries):
            for rank in range(args.top):
                j = top_indices[i, rank]
                score = top_scores[i, rank]
                snomed = snomed_concepts[j]
                writer.writerow([
                    ccam["code"],
                    ccam["description"],
                    rank + 1,
                    snomed["concept_id"],
                    snomed["concept_code"],
                    snomed["concept_name"],
                    snomed["vocabulary_id"],
                    f"{score:.4f}",
                ])

    elapsed = time.time() - t0
    total_rows = len(ccam_entries) * args.top
    print(f"\n  Wrote {total_rows} rows to {args.output}")
    print(f"  Total time: {elapsed:.1f}s")

    # Show sample results
    print()
    print("=" * 60)
    print("Sample results (first 3 CCAM codes, top-3)")
    print("=" * 60)
    for i in range(min(3, len(ccam_entries))):
        ccam = ccam_entries[i]
        print(f"\n  {ccam['code']}: {ccam['description']}")
        for rank in range(min(3, args.top)):
            j = top_indices[i, rank]
            score = top_scores[i, rank]
            snomed = snomed_concepts[j]
            print(f"    #{rank+1} [{score:.3f}] {snomed['concept_name']} ({snomed['vocabulary_id']} {snomed['concept_code']})")

    print(f"\n\nTo load into OPAL as reference:")
    print(f'  curl --noproxy \'*\' -s -X POST "http://localhost:8000/api/mapping/reference/upload" \\')
    print(f'    -F "name=SAPBERT_CCAM_SNOMED" -F "domain=Procedure" -F "file=@{args.output}"')


if __name__ == "__main__":
    main()
