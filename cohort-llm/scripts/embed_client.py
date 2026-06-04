"""
Embedding client for cohort-llm's RAG.

Embeddings come from the shared **opal-sapbert** runner (POST /encode), NOT from a
model bundled in this image. This keeps a single medical embedder (multilingual
SapBERT) resident in VRAM for BOTH mapping suggestions and cohort retrieval, and
lets opal-llm stay light (no torch, no embedding model baked).

SapBERT is an independent module (backend `SAPBERT_MODE`, default on). When its
runner is unreachable, RAG retrieval is unavailable and the service degrades to
extraction-only (see service.py). Configured via SAPBERT_URL / SAPBERT_RUNNER_TOKEN
— the same values the backend uses, so both clients hit the same runner.
"""
import os

import numpy as np
import requests

SAPBERT_URL = os.environ.get("SAPBERT_URL", "http://opal-sapbert:8002").rstrip("/")
SAPBERT_TOKEN = os.environ.get("SAPBERT_RUNNER_TOKEN", "")
# Identifies which model produced an index, so a stale index (e.g. a previous e5
# build, or a model swap) is detected and rebuilt rather than read with wrong vectors.
EMBED_MODEL_TAG = os.environ.get(
    "SAPBERT_MODEL", "cambridgeltl/SapBERT-UMLS-2020AB-all-lang-from-XLMR"
)
HIDDEN_SIZE = 768  # XLM-R / BERT-base


class EmbeddingClient:
    """Thin HTTP client over the opal-sapbert runner's /encode endpoint."""

    def __init__(self, url: str = SAPBERT_URL, token: str = SAPBERT_TOKEN,
                 batch_size: int = 256, timeout: float = 600.0):
        self.url = url.rstrip("/")
        self.headers = {"X-Sapbert-Token": token} if token else {}
        self.batch_size = batch_size
        self.timeout = timeout
        self.model_tag = EMBED_MODEL_TAG

    def health(self) -> bool:
        """True only when the runner is reachable AND the model is loaded."""
        try:
            r = requests.get(f"{self.url}/health", headers=self.headers, timeout=5)
            return r.status_code == 200 and bool(r.json().get("model_loaded"))
        except (requests.RequestException, ValueError):
            return False

    def encode(self, texts: list[str], normalize: bool = True) -> np.ndarray:
        """Encode texts via the runner, batched. Returns (n, HIDDEN_SIZE) float32."""
        if not texts:
            return np.zeros((0, HIDDEN_SIZE), dtype="float32")
        out = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            resp = requests.post(
                f"{self.url}/encode",
                json={"texts": batch, "normalize": normalize},
                headers=self.headers, timeout=self.timeout,
            )
            resp.raise_for_status()
            out.append(np.asarray(resp.json()["embeddings"], dtype="float32"))
        return np.vstack(out) if out else np.zeros((0, HIDDEN_SIZE), dtype="float32")
