# opal-llm : self-contained cohort-from-text service.
# Bakes Ollama + Qwen2.5-7B + multilingual-e5 + our code into one image.
# At runtime it reads OPAL's source_value_cache (opal-db) to build per-CDM indexes.
FROM ollama/ollama:latest

ENV DEBIAN_FRONTEND=noninteractive \
    OLLAMA_MODELS=/models \
    HF_HOME=/hf-cache \
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

# Torch (CUDA 11.8) first, then the rest
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu118
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the Qwen model into the image layer (/models, not a volume path)
RUN ollama serve & \
    sleep 5 && \
    ollama pull qwen2.5:7b-instruct-q4_K_M && \
    pkill -f "ollama serve"

# Bake the e5 embedding model into the image (HF cache)
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('intfloat/multilingual-e5-base')"

# Application code
COPY scripts/ /app/
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8001
# Override ollama image's default entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
