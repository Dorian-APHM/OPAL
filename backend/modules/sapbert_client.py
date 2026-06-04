"""
Thin HTTP client for the opal-sapbert runner.

The backend owns the read-only CDM connections and the app DB; this module only
relays data to the dedicated SapBERT service (encoding + top-K cosine) and returns
the rows to store in `sapbert_mappings`. The service never touches any database.
See sapbert-tools/ for the runner.

Flow per (cdm, domain):
    key = targets_key(cdm_name, domain)
    index_targets(key, standard_concepts)   # encode + cache target embeddings
    rows = match_sources(key, labelled_source_values, top_k)  # -> sapbert_mappings rows
"""
import logging

import httpx

from config import SAPBERT_ENABLED, SAPBERT_RUNNER_TOKEN, SAPBERT_URL

logger = logging.getLogger(__name__)

# Encoding a domain's full standard vocabulary (100k+ concepts) can take minutes
# on GPU, so read timeouts are generous while connect stays short.
_INDEX_TIMEOUT = httpx.Timeout(connect=10.0, read=1800.0, write=120.0, pool=10.0)
# The similarity matmul over a full domain vocabulary (millions of concepts) is
# CPU-bound; allow a generous read window so a large /match never times out and
# leaves an orphaned computation blocking the (single-threaded) runner.
_MATCH_TIMEOUT = httpx.Timeout(connect=10.0, read=3600.0, write=120.0, pool=10.0)
_HEALTH_TIMEOUT = httpx.Timeout(5.0)

# Cap target concepts per /index call to keep request bodies reasonable; the
# service appends chunks (reset on the first one). Smaller chunks also make
# cancellation responsive (the cancel flag is polled between chunks).
_INDEX_CHUNK = 5000


class SapbertError(RuntimeError):
    """Raised when the SapBERT runner is unreachable or returns an error."""


class SapbertCancelled(Exception):
    """Raised to abort an in-progress build (checked between /index chunks)."""


def is_enabled() -> bool:
    return SAPBERT_ENABLED


def targets_key(cdm_name: str, domain: str) -> str:
    """Stable cache key for a (cdm, domain) target index."""
    return f"{cdm_name}__{domain}"


def _headers() -> dict:
    return {"X-Sapbert-Token": SAPBERT_RUNNER_TOKEN}


def _post(path: str, payload: dict, timeout: httpx.Timeout) -> dict:
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(f"{SAPBERT_URL}{path}", json=payload, headers=_headers())
    except httpx.HTTPError as exc:
        raise SapbertError(f"SapBERT runner unreachable: {exc}") from exc
    if resp.status_code >= 400:
        raise SapbertError(f"SapBERT runner {path} -> {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def health() -> dict:
    """Liveness + which (cdm, domain) indexes are cached. Raises SapbertError if down."""
    try:
        with httpx.Client(timeout=_HEALTH_TIMEOUT) as client:
            resp = client.get(f"{SAPBERT_URL}/health", headers=_headers())
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        raise SapbertError(f"SapBERT runner unreachable: {exc}") from exc


def index_targets(key: str, targets: list[dict], cancel_check=None) -> int:
    """Encode and cache target concept embeddings for a (cdm, domain) key.

    `targets` items: {concept_id, concept_code, concept_name, vocabulary_id}.
    Sent in chunks; the first chunk resets the index. `cancel_check` (if given) is
    polled between chunks and raises SapbertCancelled to abort. Returns total indexed.
    """
    if not targets:
        return 0
    total = 0
    for i in range(0, len(targets), _INDEX_CHUNK):
        if cancel_check and cancel_check():
            raise SapbertCancelled()
        out = _post(
            "/index",
            {"targets_key": key, "targets": targets[i : i + _INDEX_CHUNK], "reset": i == 0},
            _INDEX_TIMEOUT,
        )
        total = out.get("indexed", total)
    return total


def match_sources(key: str, sources: list[dict], top_k: int = 5) -> list[dict]:
    """Top-K match of source labels against the cached index for `key`.

    `sources` items: {code, name}. Returns rows ready for sapbert_mappings:
    {source_code, source_name, rank, target_concept_id, target_concept_code,
     target_concept_name, target_vocabulary_id, similarity}.
    """
    if not sources:
        return []
    out = _post(
        "/match",
        {"targets_key": key, "sources": sources, "top_k": top_k},
        _MATCH_TIMEOUT,
    )
    return out.get("mappings", [])
