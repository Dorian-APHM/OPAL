"""
llm.py — minimal OpenAI-compatible chat client.

A single code path for every LLM backend that speaks the OpenAI Chat Completions
API (`POST {base_url}/chat/completions`):
  - embedded mode  : Ollama's built-in OpenAI endpoint (http://localhost:11434/v1)
  - on-premise mode: the institution's own endpoint (vLLM, LocalAI, TGI, Ollama /v1…)

The OPAL backend decides which backend to use and passes {base_url, model, api_key}
to the service per request; this module only speaks the protocol. The RAG layer
(e5 + index) does NOT use this — only the two generation steps (extract, expand).
"""
import json
import os

import requests

# Defaults for the embedded ("on") mode — Ollama's OpenAI-compatible endpoint.
EMBEDDED_BASE_URL = os.environ.get("COHORT_LLM_EMBEDDED_BASE_URL", "http://localhost:11434/v1")
EMBEDDED_MODEL = os.environ.get("COHORT_LLM_EMBEDDED_MODEL", "qwen2.5:7b-instruct-q4_K_M")


class LLMError(RuntimeError):
    """Raised when the LLM endpoint is unreachable or returns an error/garbage."""


class LLMClient:
    def __init__(self, base_url: str, model: str, api_key: str | None = None,
                 timeout: float = 120.0):
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.api_key = api_key or ""
        self.timeout = timeout

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def complete(self, system: str, user: str, *, json_mode: bool = False,
                 max_tokens: int = 512, timeout: float | None = None) -> str:
        """Return the assistant message content as a plain string."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            # Honored by Ollama /v1, vLLM, LocalAI… Non-strict endpoints are tolerated
            # by _loads_tolerant() below (the system prompt also mandates pure JSON).
            payload["response_format"] = {"type": "json_object"}
        try:
            r = requests.post(f"{self.base_url}/chat/completions", json=payload,
                              headers=self._headers(), timeout=timeout or self.timeout)
        except requests.RequestException as e:
            raise LLMError(f"LLM unreachable at {self.base_url}: {e}") from e
        if r.status_code >= 400:
            raise LLMError(f"LLM error {r.status_code}: {r.text[:300]}")
        try:
            return r.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError) as e:
            raise LLMError(f"unexpected LLM response: {r.text[:300]}") from e

    def complete_json(self, system: str, user: str, *, max_tokens: int = 800,
                      timeout: float | None = None) -> dict:
        """complete() in JSON mode, parsed tolerantly into a dict."""
        return _loads_tolerant(self.complete(system, user, json_mode=True,
                                             max_tokens=max_tokens, timeout=timeout))


def embedded_client(timeout: float = 120.0) -> LLMClient:
    """Client for the bundled local LLM (Ollama OpenAI-compatible endpoint)."""
    return LLMClient(EMBEDDED_BASE_URL, EMBEDDED_MODEL, api_key=None, timeout=timeout)


def _loads_tolerant(txt: str) -> dict:
    """Parse JSON, tolerating ```json fences and surrounding prose from lax endpoints."""
    txt = (txt or "").strip()
    if not txt:
        return {}
    if txt.startswith("```"):
        parts = txt.split("```")
        txt = parts[1] if len(parts) >= 2 else txt.strip("`")
        if txt.lstrip().lower().startswith("json"):
            txt = txt.lstrip()[4:]
        txt = txt.strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        a, b = txt.find("{"), txt.rfind("}")
        if a != -1 and b > a:
            return json.loads(txt[a:b + 1])
        raise
