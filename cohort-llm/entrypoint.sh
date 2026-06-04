#!/bin/bash
set -e

# COHORT_LLM_MODE drives whether the bundled local LLM (Ollama) runs:
#   embedded   -> start Ollama and pull the model on first run (persisted in the volume)
#   on-premise -> no Ollama; generation uses the external LLM the backend passes per request
MODE="${COHORT_LLM_MODE:-embedded}"

if [ "$MODE" = "embedded" ]; then
  export OLLAMA_MODELS="${OLLAMA_MODELS:-/models}"
  MODEL="${COHORT_LLM_EMBEDDED_MODEL:-qwen2.5:7b-instruct-q4_K_M}"

  echo "[embedded] starting Ollama..."
  ollama serve &
  echo "[embedded] waiting for Ollama..."
  until curl -sf http://localhost:11434/ >/dev/null 2>&1; do sleep 1; done

  # Pull the model if absent (first run only; cached in the OLLAMA_MODELS volume).
  if ! ollama list 2>/dev/null | grep -q "$MODEL"; then
    echo "[embedded] pulling model $MODEL (first run, this can take a while)..."
    ollama pull "$MODEL"
  fi
  echo "[embedded] Ollama ready (model: $MODEL)."
else
  echo "[on-premise] Ollama disabled; generation uses the external LLM provided per request."
fi

# Start the FastAPI service (RAG orchestration + /draft; embeddings via opal-sapbert).
exec uvicorn service:app --host 0.0.0.0 --port 8001
