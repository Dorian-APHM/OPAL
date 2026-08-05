# OPAL — OHDSI Runner

Self-contained image bundling the five OHDSI R quality tools **and** a small
runner API that OPAL calls to launch them. The tools run as **subprocesses** of
this service — there is **no Docker socket** and no container orchestration.

| Service          | R package            | Purpose                                |
|------------------|----------------------|----------------------------------------|
| `achilles`       | Achilles             | OMOP CDM characterization analyses     |
| `achilles-export`| Achilles             | Export results to JSON for AresIndexer |
| `dqd`            | DataQualityDashboard | Data quality checks (CDMv5.4 rules)    |
| `cdmonboarding`  | CdmOnboarding        | Onboarding report (consumes DQD output)|
| `dashboardexport`| DashboardExport      | Export Achilles results for the DARWIN Database Dashboard |

The OHDSI packages are **vendored** as tarballs under `vendor/` (corporate
proxies may block GitHub). The PostgreSQL JDBC driver is vendored under
`drivers/`.

## How OPAL uses it

The runner is **opt-in**. It is declared in the root `docker-compose.yml` behind
the `ohdsi` profile and is only started when OHDSI is enabled:

```bash
# .env: OHDSI_MODE=on and OHDSI_RUNNER_TOKEN=<openssl rand -hex 32>
docker compose --profile ohdsi up -d
```

The OPAL backend (`backend/modules/ohdsi/router.py`) is a thin HTTP client of
this service. It never touches Docker. The runner lives on a dedicated network
(`opal-ohdsi-network`) with egress to the external OMOP database only — it
cannot reach `opal-db` or Keycloak.

## Runner API (internal)

All routes except `/health` require the `X-Runner-Token` header
(`OHDSI_RUNNER_TOKEN`).

| Method & path                | Purpose                                   |
|------------------------------|-------------------------------------------|
| `GET  /health`               | Liveness (public)                         |
| `POST /jobs`                 | Launch a job (service + CDM connection)   |
| `GET  /jobs?service=`        | List jobs (newest first)                  |
| `GET  /jobs/{id}`            | Job metadata + status                     |
| `GET  /jobs/{id}/logs?offset=`| Incremental logs                         |
| `POST /jobs/{id}/cancel`     | Cancel a running job                      |
| `GET  /files/{path}`         | Browse / download output files            |

### Execution contract (env vars)

The R scripts are parametrised entirely by environment variables, set per job by
the runner:

```
DB_SYSTEM, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD,
CDM_SCHEMA, RESULTS_SCHEMA, VOCABULARY_SCHEMA,
CDM_VERSION, CDM_SOURCE_NAME, SMALL_CELL_COUNT,
PATH_TO_DRIVER, OUTPUT_DIR  (+ DQD_INPUT_DIR for cdmonboarding)
```

Job state is persisted in SQLite (on the `opal_ohdsi_data` volume) so it
survives restarts and supports concurrent runs across CDMs. Jobs interrupted by
a restart are reconciled to `error` on startup.

## Build

```bash
# No proxy
docker compose --profile ohdsi build

# Behind a corporate proxy with SSL interception
docker compose --profile ohdsi build \
  --build-arg HTTP_PROXY=http://localhost:3128 \
  --build-arg HTTPS_PROXY=http://localhost:3128 \
  --build-arg PROXY_CA_HOST=<proxy-ip> \
  --build-arg PROXY_CA_PORT=<proxy-port>
```

## Layout

```
ohdsi-tools/
├── Dockerfile               R 4.3.2 + OHDSI packages + Python runner
├── runner/
│   ├── server.py            FastAPI job API (subprocess launcher)
│   ├── requirements.txt
│   └── tests/test_runner.py End-to-end lifecycle tests (no R needed)
├── drivers/
│   └── postgresql-42.7.4.jar
├── scripts/
│   ├── config/              DQD CDMv5.4 rule sets
│   ├── run_achilles.R
│   ├── run_achilles_export.R
│   ├── run_dqd.R
│   └── run_cdmonboarding.R
└── vendor/                  OHDSI R package tarballs
```

## Outputs

Each run writes to `/data/output/<cdm_name>/<service>/` inside the runner
(persisted on the `opal_ohdsi_data` volume). The frontend reads/serves them via
`/api/ohdsi/files/`, which the backend relays from the runner's `/files/`.
