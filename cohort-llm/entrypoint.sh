#!/bin/bash
set -e

# Start Ollama (serves the baked Qwen model) in the background
export OLLAMA_MODELS=/models
ollama serve &

# Wait for Ollama to accept connections
echo "Waiting for Ollama..."
until curl -sf http://localhost:11434/ >/dev/null 2>&1; do
  sleep 1
done
echo "Ollama ready."

# Start the FastAPI service (loads e5, serves /draft)
exec uvicorn service:app --host 0.0.0.0 --port 8001
