"""
OPAL SapBERT Runner — internal embedding/match API (FastAPI :8002).

The OPAL backend (which owns the read-only CDM connections) sends:
  - target standard concepts of a (cdm, domain)  -> POST /index   (encoded + cached)
  - source labels to map                         -> POST /match   (top-K cosine)
and writes the returned rows into OPAL's `sapbert_mappings` table. This service
NEVER touches the CDM or the app DB — it is pure compute over a model baked into
the image, plus an embeddings cache on a volume (one folder per targets_key).

Security: a shared bearer token (SAPBERT_RUNNER_TOKEN) gates every route via the
`X-Sapbert-Token` header. Meant to live on an internal network reachable only by
the backend.
"""
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from encoder import SapbertEncoder

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL_NAME = os.getenv("SAPBERT_MODEL", "cambridgeltl/SapBERT-UMLS-2020AB-all-lang-from-XLMR")
DEVICE = os.getenv("SAPBERT_DEVICE", "cuda")
RUNNER_TOKEN = os.getenv("SAPBERT_RUNNER_TOKEN", "")
CACHE_DIR = Path(os.getenv("SAPBERT_CACHE_DIR", "/cache"))
BATCH_SIZE = int(os.getenv("SAPBERT_BATCH_SIZE", "128"))

CACHE_DIR.mkdir(parents=True, exist_ok=True)

_KEY_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_key(key: str) -> str:
    """Filesystem-safe targets_key (e.g. 'mycdm__Procedure')."""
    cleaned = _KEY_RE.sub("_", key).strip("_")
    if not cleaned:
        raise HTTPException(400, "empty targets_key")
    return cleaned[:200]


def _key_dir(key: str, *, create: bool = False) -> Path:
    d = CACHE_DIR / _safe_key(key)
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


_state: dict = {"encoder": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"Loading SapBERT model {MODEL_NAME} (requested device={DEVICE})...", flush=True)
    _state["encoder"] = SapbertEncoder(MODEL_NAME, device=DEVICE, batch_size=BATCH_SIZE)
    print(f"Model loaded on {_state['encoder'].device}.", flush=True)
    yield
    _state.clear()


app = FastAPI(title="opal-sapbert", lifespan=lifespan)


def require_token(x_sapbert_token: str = Header(default="")) -> None:
    if RUNNER_TOKEN and x_sapbert_token != RUNNER_TOKEN:
        raise HTTPException(401, "invalid or missing X-Sapbert-Token")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class Target(BaseModel):
    concept_id: int
    concept_code: str = ""
    concept_name: str
    vocabulary_id: str = ""


class IndexRequest(BaseModel):
    targets_key: str          # e.g. f"{cdm_name}__{domain}"
    targets: list[Target]
    reset: bool = True         # True: replace the index; False: append a chunk


class Source(BaseModel):
    code: str
    name: str


class MatchRequest(BaseModel):
    targets_key: str
    sources: list[Source]
    top_k: int = 5


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    enc = _state.get("encoder")
    indexed = [p.name for p in CACHE_DIR.iterdir() if p.is_dir()] if CACHE_DIR.exists() else []
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "model_loaded": enc is not None,
        "device": enc.device if enc else None,
        "indexed": indexed,
    }


@app.post("/index")
def index(req: IndexRequest, _=Depends(require_token)):
    """Encode and cache target concept embeddings for a (cdm, domain) key."""
    enc = _state["encoder"]
    if enc is None:
        raise HTTPException(503, "model not loaded yet")
    d = _key_dir(req.targets_key, create=True)
    emb_path, meta_path = d / "embeddings.npy", d / "metadata.jsonl"

    embs = enc.encode([t.concept_name for t in req.targets])
    if not req.reset and emb_path.exists():
        prev = np.load(emb_path)
        embs = np.vstack([prev, embs]) if embs.shape[0] else prev
        meta_mode = "a"
    else:
        meta_mode = "w"

    np.save(emb_path, embs)
    with open(meta_path, meta_mode, encoding="utf-8") as f:
        for t in req.targets:
            f.write(json.dumps(t.model_dump(), ensure_ascii=False) + "\n")

    total = int(embs.shape[0])
    return {"targets_key": req.targets_key, "added": len(req.targets), "indexed": total}


@app.post("/match")
def match(req: MatchRequest, _=Depends(require_token)):
    """Encode source labels and return top-K cosine matches against the index."""
    enc = _state["encoder"]
    if enc is None:
        raise HTTPException(503, "model not loaded yet")
    d = _key_dir(req.targets_key)
    emb_path, meta_path = d / "embeddings.npy", d / "metadata.jsonl"
    if not emb_path.exists():
        raise HTTPException(404, f"no index for targets_key '{req.targets_key}' — call /index first")

    target_embs = np.load(emb_path)
    with open(meta_path, encoding="utf-8") as f:
        targets = [json.loads(line) for line in f]

    src_embs = enc.encode([s.name for s in req.sources])
    idx, scores = enc.topk(src_embs, target_embs, req.top_k)

    mappings = []
    for i, src in enumerate(req.sources):
        for rank in range(idx.shape[1]):
            t = targets[int(idx[i, rank])]
            mappings.append({
                "source_code": src.code,
                "source_name": src.name,
                "rank": rank + 1,
                "target_concept_id": t["concept_id"],
                "target_concept_code": t.get("concept_code", ""),
                "target_concept_name": t.get("concept_name", ""),
                "target_vocabulary_id": t.get("vocabulary_id", ""),
                "similarity": round(float(scores[i, rank]), 4),
            })
    return {"targets_key": req.targets_key, "count": len(mappings), "mappings": mappings}


class EncodeRequest(BaseModel):
    texts: list[str]
    normalize: bool = True     # L2-normalize so callers can dot-product as cosine


@app.post("/encode")
def encode(req: EncodeRequest, _=Depends(require_token)):
    """Generic embedding endpoint — encode arbitrary texts into SapBERT CLS vectors.

    Stateless (no cache, no targets_key): unlike /index + /match (mapping's batch
    precompute), this serves cohort-llm's RAG, which owns its own per-CDM index and
    only needs raw vectors — for building that index and for encoding live queries.
    One medical embedder in VRAM, shared by mapping and the cohort assistant.
    """
    enc = _state["encoder"]
    if enc is None:
        raise HTTPException(503, "model not loaded yet")
    embs = enc.encode(req.texts)                       # (n, hidden) float32, CLS pooled
    if req.normalize and embs.shape[0]:
        embs = embs / (np.linalg.norm(embs, axis=1, keepdims=True) + 1e-12)
    return {
        "model": MODEL_NAME,
        "dim": enc.hidden_size,
        "count": int(embs.shape[0]),
        "embeddings": embs.astype(np.float32).tolist(),
    }
