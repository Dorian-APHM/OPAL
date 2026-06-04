"""
Relay to the opal-llm microservice (natural-language -> cohort draft).

The browser cannot reach opal-llm:8001 directly (internal compose network), so the
backend forwards authenticated requests to it. The feature is opt-in (COHORT_LLM_MODE):

  off         -> endpoints return 503, the "AI assistant" tab is hidden
  embedded    -> opal-llm uses its bundled local model
  on-premise  -> opal-llm uses the institution's own OpenAI-compatible LLM, whose
                 endpoint/model/key are configured here (Settings, admin) and stored
                 Fernet-encrypted; the backend decrypts and injects them per request.
"""
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import AUTH_ENABLED, COHORT_LLM_ENABLED, COHORT_LLM_MODE, COHORT_LLM_URL
from db.app_db import get_db
from db.models import CohortLlmConfig
from utils.cdm_helper import check_cdm_access
from utils.crypto import decrypt_password, encrypt_password, DecryptionError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cohort-llm", tags=["cohort-llm"])

# /draft can take ~30s on the first request for a CDM (index build) + LLM calls.
_TIMEOUT = httpx.Timeout(180.0, connect=5.0)
# An explicit RAG rebuild re-encodes the whole source_value_cache via opal-sapbert;
# it can take a couple of minutes on a large CDM.
_REBUILD_TIMEOUT = httpx.Timeout(600.0, connect=5.0)


def _require_enabled() -> None:
    if not COHORT_LLM_ENABLED:
        raise HTTPException(503, "Cohort-LLM is disabled (set COHORT_LLM_MODE=embedded|on-premise)")


def _require_admin(request: Request) -> None:
    if not AUTH_ENABLED:  # dev/local mode grants admin (S02: restricted to localhost)
        return
    user = getattr(request.state, "user", {}) or {}
    if "admin" not in (user.get("roles", []) or []):
        raise HTTPException(403, "Admin only")


def _load_onprem_llm(db: Session) -> dict:
    """Return the on-premise LLM payload {base_url, model, api_key} or raise 503."""
    cfg = db.query(CohortLlmConfig).filter(CohortLlmConfig.id == 1).first()
    if not cfg or not cfg.base_url or not cfg.model:
        raise HTTPException(
            503, "On-premise LLM is not configured. Set its endpoint in Settings (admin)."
        )
    api_key = ""
    if cfg.api_key_encrypted:
        try:
            api_key = decrypt_password(cfg.api_key_encrypted)
        except DecryptionError:
            raise HTTPException(500, "Stored LLM API key could not be decrypted.")
    return {"base_url": cfg.base_url, "model": cfg.model, "api_key": api_key}


# ---------------------------------------------------------------------------
# Feature flag + settings
# ---------------------------------------------------------------------------
@router.get("/config")
def get_config() -> dict:
    """Feature flag for the frontend. Always available (even when disabled)."""
    return {"enabled": COHORT_LLM_ENABLED, "mode": COHORT_LLM_MODE}


class LlmSettings(BaseModel):
    base_url: str | None = Field(default=None)
    model: str | None = Field(default=None)
    # Write-only: provided to set/rotate the key. Never returned by GET.
    api_key: str | None = Field(default=None)


@router.get("/settings")
def get_settings(request: Request, db: Session = Depends(get_db)) -> dict:
    """Return the on-premise LLM config (admin only). The API key is masked."""
    _require_admin(request)
    cfg = db.query(CohortLlmConfig).filter(CohortLlmConfig.id == 1).first()
    return {
        "mode": COHORT_LLM_MODE,
        "base_url": cfg.base_url if cfg else None,
        "model": cfg.model if cfg else None,
        "has_api_key": bool(cfg and cfg.api_key_encrypted),
    }


@router.put("/settings")
def put_settings(body: LlmSettings, request: Request, db: Session = Depends(get_db)) -> dict:
    """Upsert the on-premise LLM config (admin only)."""
    _require_admin(request)
    if body.base_url and not body.base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "base_url must start with http:// or https://")

    user = getattr(request.state, "user", {}) or {}
    cfg = db.query(CohortLlmConfig).filter(CohortLlmConfig.id == 1).first()
    if not cfg:
        cfg = CohortLlmConfig(id=1)
        db.add(cfg)
    cfg.base_url = (body.base_url or "").strip() or None
    cfg.model = (body.model or "").strip() or None
    # api_key: None -> keep existing; "" -> clear; value -> encrypt.
    if body.api_key is not None:
        cfg.api_key_encrypted = encrypt_password(body.api_key) if body.api_key else None
    cfg.updated_by = user.get("preferred_username", "anonymous")
    db.commit()
    return {"ok": True, "has_api_key": bool(cfg.api_key_encrypted)}


# ---------------------------------------------------------------------------
# Inference relay
# ---------------------------------------------------------------------------
class DraftRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    cdm_name: str = Field(..., min_length=1)


@router.post("/draft")
def draft(req: DraftRequest, request: Request, db: Session = Depends(get_db)):
    """Forward a natural-language cohort prompt to opal-llm and return the draft."""
    _require_enabled()
    check_cdm_access(request, req.cdm_name)
    user = getattr(request.state, "user", {}) or {}
    logger.info("cohort-llm draft by %s on CDM %s (mode=%s)",
                user.get("preferred_username", "anonymous"), req.cdm_name, COHORT_LLM_MODE)

    payload: dict = {"prompt": req.prompt, "cdm_name": req.cdm_name}
    if COHORT_LLM_MODE == "on-premise":
        payload["llm"] = _load_onprem_llm(db)  # embedded mode omits this -> service default

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(f"{COHORT_LLM_URL}/draft", json=payload)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"opal-llm error: {e.response.text[:300]}")
    except httpx.RequestError as e:
        raise HTTPException(503, f"opal-llm unreachable: {e}")


class RebuildRequest(BaseModel):
    cdm_name: str = Field(..., min_length=1)


@router.post("/rebuild")
def rebuild_rag(req: RebuildRequest, request: Request):
    """Force-rebuild the RAG index for a CDM (admin only). Relays to opal-llm.

    Re-encodes the CDM's source_value_cache via opal-sapbert and replaces the cached
    index. The Source Value Cache must be populated first. Long-running (minutes on a
    large CDM). The lazy build on first /draft does the same — this just pre-warms it
    and refreshes a stale index after the cache is updated.
    """
    _require_enabled()
    _require_admin(request)
    check_cdm_access(request, req.cdm_name)
    user = getattr(request.state, "user", {}) or {}
    logger.info("cohort-llm RAG rebuild by %s on CDM %s",
                user.get("preferred_username", "anonymous"), req.cdm_name)
    try:
        with httpx.Client(timeout=_REBUILD_TIMEOUT) as client:
            resp = client.post(f"{COHORT_LLM_URL}/rebuild/{req.cdm_name}")
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"opal-llm error: {e.response.text[:300]}")
    except httpx.RequestError as e:
        raise HTTPException(503, f"opal-llm unreachable: {e}")


@router.get("/health")
def health():
    """Proxy opal-llm health (useful to check the LLM service from the UI)."""
    _require_enabled()
    try:
        with httpx.Client(timeout=httpx.Timeout(5.0)) as client:
            resp = client.get(f"{COHORT_LLM_URL}/health")
        return resp.json()
    except httpx.RequestError as e:
        raise HTTPException(503, f"opal-llm unreachable: {e}")
