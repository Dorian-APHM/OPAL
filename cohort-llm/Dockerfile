# opal-llm : cohort-from-text service (RAG orchestration + optional bundled LLM).
# Embeddings are NOT produced here — the RAG calls the shared opal-sapbert runner
# (POST /encode), so this image carries no torch and no embedding model. The
# generation model is also NOT baked:
#   - embedded mode   -> Ollama pulls the model on first run (persisted in a volume)
#   - on-premise mode -> Ollama is not started; an external LLM is used per request
# At runtime it reads OPAL's source_value_cache (opal-db) to build per-CDM indexes.
FROM ollama/ollama:latest

ENV DEBIAN_FRONTEND=noninteractive \
    OLLAMA_MODELS=/models \
    COHORT_LLM_INDEX_CACHE=/app/index_cache \
    PYTHONUNBUFFERED=1

# Python + build essentials (ollama/ollama is Ubuntu-based; use the base's python3)
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv curl \
    && rm -rf /var/lib/apt/lists/*

# Isolated venv (avoids PEP 668 "externally-managed-environment" on recent Ubuntu)
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Python deps — no torch, no embedding model (embeddings come from opal-sapbert).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# NOTE: the generation model is intentionally NOT baked here — it is pulled at
# first run in embedded mode (entrypoint.sh) into the OLLAMA_MODELS volume, and
# not used at all in on-premise mode. This keeps the image light (~no multi-GB
# model layer) and lets the embedded model be swapped via COHORT_LLM_EMBEDDED_MODEL.

# Application code
COPY scripts/ /app/
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8001
# Override ollama image's default entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
