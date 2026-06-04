# opal-sapbert : multilingual SapBERT encoder service for mapping suggestions.
# Bakes cambridgeltl/SapBERT-UMLS-2020AB-all-lang-from-XLMR (~1.1 GB) into the
# image so it works offline at runtime. The OPAL backend calls it over HTTP to
# pre-compute top-K source→standard-concept mappings (stored in sapbert_mappings).
# Pure compute: no DB and no CDM access — only a model + an embeddings cache volume.
FROM python:3.11-slim

ENV HF_HOME=/hf-cache \
    SAPBERT_CACHE_DIR=/cache \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Torch (CUDA 11.8) first — the wheel bundles the CUDA runtime, so the GPU works
# with the nvidia container runtime (see deploy.reservations in docker-compose).
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu118
COPY runner/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the multilingual SapBERT model into the image (HF cache under HF_HOME).
# Keep this ARG default in sync with SAPBERT_MODEL at runtime, otherwise the
# service would try to download a different model on first request.
ARG SAPBERT_MODEL=cambridgeltl/SapBERT-UMLS-2020AB-all-lang-from-XLMR
RUN python -c "from transformers import AutoModel, AutoTokenizer; \
    AutoModel.from_pretrained('${SAPBERT_MODEL}'); \
    AutoTokenizer.from_pretrained('${SAPBERT_MODEL}')"

COPY runner/ /app/

EXPOSE 8002
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8002"]
