"""
opal-llm service — FastAPI :8001

POST /draft {prompt, cdm_name}
  → extract.py (LLM): prompt FR → {demographics, criteria[]} (temporal/value/negation)
  → retrieve.py (RAG): per criterion label → concept-set (all matching source_values)
  → returns the enriched cohort draft, ready to map onto OPAL's cohort builder.

The e5 model is loaded once at startup. Per-CDM indexes are built lazily from
opal-db's source_value_cache and cached on disk (index_builder).
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

import extract
import index_builder
from retrieve import Retriever, expand_label

# Shared state
_state: dict = {"model": None, "retrievers": {}}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"Loading embedding model {index_builder.MODEL_NAME}...")
    device = "cuda" if os.environ.get("COHORT_LLM_DEVICE", "cuda") == "cuda" else "cpu"
    _state["model"] = SentenceTransformer(index_builder.MODEL_NAME, device=device)
    print(f"Model loaded on {device}.")
    yield
    _state["retrievers"].clear()


app = FastAPI(title="opal-llm", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def get_retriever(cdm_name: str) -> Retriever:
    """Lazy per-CDM retriever (builds/loads index from opal-db on first use)."""
    cache = _state["retrievers"]
    if cdm_name not in cache:
        cache[cdm_name] = Retriever(cdm_name, _state["model"])
    return cache[cdm_name]


class DraftRequest(BaseModel):
    prompt: str
    cdm_name: str


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": _state["model"] is not None,
            "cdms_indexed": list(_state["retrievers"].keys())}


@app.post("/draft")
def draft(req: DraftRequest):
    if not req.prompt.strip():
        raise HTTPException(400, "prompt is empty")
    try:
        extracted = extract.extract_cohort(req.prompt)
    except Exception as e:
        raise HTTPException(502, f"extraction failed: {e}")

    retriever = get_retriever(req.cdm_name)

    for crit in extracted.get("criteria", []):
        label = crit.get("label", "").strip()
        domain = crit.get("domain")
        if not label:
            crit["concept_sets"] = []
            continue
        expansion = expand_label(label)
        crit["expansion"] = expansion
        groups = retriever.search_concept_set(expansion, domain=domain)
        crit["concept_sets"] = groups
        crit["no_match"] = len(groups) == 0  # UI shows a warning card when true

    return extracted


@app.post("/rebuild/{cdm_name}")
def rebuild(cdm_name: str):
    """Force-rebuild the index for a CDM from the current opal-db cache."""
    index_builder.load_or_build(cdm_name, _state["model"], force=True)
    _state["retrievers"].pop(cdm_name, None)  # drop stale in-memory retriever
    return {"status": "rebuilt", "cdm_name": cdm_name}
