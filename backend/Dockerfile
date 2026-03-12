FROM python:3.12-slim

ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ENV http_proxy=${HTTP_PROXY}
ENV https_proxy=${HTTPS_PROXY}

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org -r requirements.txt

# Copy application code
COPY . .

# Clear proxy from runtime env
ENV http_proxy=""
ENV https_proxy=""

# Create non-root user and required directories
RUN addgroup --system opal && adduser --system --ingroup opal opal \
    && mkdir -p /app/data /app/logs /app/ohdsi_output \
    && chown -R opal:opal /app/data /app/logs /app/ohdsi_output

USER opal

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
