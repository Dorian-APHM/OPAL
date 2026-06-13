FROM python:3.12-slim

ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ENV http_proxy=${HTTP_PROXY}
ENV https_proxy=${HTTPS_PROXY}

WORKDIR /app

# System runtime libs. unixodbc is the ODBC driver manager pyodbc loads at runtime
# for SQL Server CDM connections (the Microsoft msodbcsql18 driver must be added
# separately to actually reach a SQL Server instance). Oracle uses python-oracledb
# thin mode, which needs no Oracle client. PostgreSQL (psycopg2) needs nothing here.
RUN apt-get update \
    && apt-get install -y --no-install-recommends unixodbc \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org -r requirements.txt

# Copy application code
COPY . .

# Clear proxy from runtime env (both cases — Docker sets both)
ENV http_proxy="" \
    https_proxy="" \
    HTTP_PROXY="" \
    HTTPS_PROXY="" \
    NO_PROXY="" \
    no_proxy=""

# Create non-root user and required directories
RUN addgroup --system opal && adduser --system --ingroup opal opal \
    && mkdir -p /app/data /app/logs /app/ohdsi_output \
    && chown -R opal:opal /app/data /app/logs /app/ohdsi_output

USER opal

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
