"""
opal-llm service — FastAPI :8001

POST /draft {prompt, cdm_name}
  → extract.py (LLM): prompt FR → {demographics, criteria[]} (temporal/value/negation)
  → retrieve.py (RAG): per criterion label → concept-set (all matching source_values)
  → returns the enriched cohort draft, ready to map onto OPAL's cohort builder.

Embeddings are served by the shared opal-sapbert runner (no model loaded here).
Per-CDM indexes are built lazily from opal-db's source_value_cache and cached on
disk (index_builder), then matched in-process. When the runner is down/off, the
RAG is unavailable and /draft returns extraction-only (retrieval_unavailable=true).
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import extract
import index_builder
from embed_client import EmbeddingClient
from llm import LLMClient, embedded_client
from retrieve import Retriever, expand_label, expand_drug_terms

# Shared state
_state: dict = {"embed": None, "retrievers": {}}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Embeddings are served by the shared opal-sapbert runner — nothing to load here.
    _state["embed"] = EmbeddingClient()
    reachable = _state["embed"].health()
    print(f"Embeddings via opal-sapbert ({index_builder.MODEL_NAME}) at "
          f"{_state['embed'].url} — reachable={reachable}", flush=True)
    if not reachable:
        print("[warn] opal-sapbert not reachable yet; RAG retrieval is unavailable "
              "until it comes up (criteria extraction still works).", flush=True)
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
        cache[cdm_name] = Retriever(cdm_name, _state["embed"])
    return cache[cdm_name]


class LlmConfig(BaseModel):
    """On-premise LLM connection, injected per request by the OPAL backend.
    Absent → the service uses its embedded (bundled) local model."""
    base_url: str
    model: str
    api_key: str | None = None


class DraftRequest(BaseModel):
    prompt: str
    cdm_name: str
    llm: LlmConfig | None = None


def _client_for(req: "DraftRequest") -> LLMClient:
    """Per-request LLM: the backend's on-premise endpoint, else the embedded model."""
    if req.llm:
        return LLMClient(req.llm.base_url, req.llm.model, req.llm.api_key)
    return embedded_client()


@app.get("/health")
def health():
    embed = _state.get("embed")
    return {"status": "ok",
            "embeddings_backend": "opal-sapbert",
            "sapbert_reachable": embed.health() if embed else False,
            "mode": os.environ.get("COHORT_LLM_MODE", "embedded"),
            "cdms_indexed": list(_state["retrievers"].keys())}


@app.post("/draft")
def draft(req: DraftRequest):
    if not req.prompt.strip():
        raise HTTPException(400, "prompt is empty")
    client = _client_for(req)
    try:
        extracted = extract.extract_cohort(req.prompt, client)
    except Exception as e:
        raise HTTPException(502, f"extraction failed: {e}")

    # SapBERT is an independent module: when its runner is down/off, retrieval is
    # unavailable and we return the extracted criteria without concept-sets (the UI
    # shows a banner; the user fills concept-sets manually). Extraction still works.
    embed_ok = _state["embed"].health()
    extracted["retrieval_unavailable"] = not embed_ok
    retriever = None
    if embed_ok:
        try:
            retriever = get_retriever(req.cdm_name)
        except Exception as e:
            raise HTTPException(502, f"index build failed: {e}")

    for crit in extracted.get("criteria", []):
        label = crit.get("label", "").strip()
        if not label:
            crit["concept_sets"] = []
            continue
        if retriever is None:
            crit["concept_sets"] = []
            crit["retrieval_unavailable"] = True
            continue
        domain = crit.get("domain")
        if domain == "Drug":
            # A drug term (molecule, brand, or therapeutic class) -> representative
            # molecules. SapBERT matches molecule names well; the ATC grouping then
            # returns the whole therapeutic family ("anti-inflammatoire" -> the AINS
            # across M01A*). Each term is a separate query item (max score per concept).
            molecules = expand_drug_terms(label, client)
            crit["expansion"] = ", ".join(molecules)
            queries = [label, *molecules]
        else:
            expansion = expand_label(label, client)
            crit["expansion"] = expansion
            # raw avoids expansion drift, expansion covers abbreviations/synonyms
            queries = [label, expansion]
        groups = retriever.search_concept_set(queries, domain=domain)
        crit["concept_sets"] = groups
        crit["no_match"] = len(groups) == 0  # UI shows a warning card when true

    return extracted


@app.post("/rebuild/{cdm_name}")
def rebuild(cdm_name: str):
    """Force-rebuild the index for a CDM from the current opal-db cache."""
    index_builder.load_or_build(cdm_name, _state["embed"], force=True)
    _state["retrievers"].pop(cdm_name, None)  # drop stale in-memory retriever
    return {"status": "rebuilt", "cdm_name": cdm_name}
