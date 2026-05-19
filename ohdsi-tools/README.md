# OPAL — OHDSI Quality Tools

Self-contained build of the four OHDSI R-based quality tools that OPAL orchestrates from the **OHDSI** page:

| Service          | R package            | Purpose                              |
|------------------|----------------------|--------------------------------------|
| `achilles`       | Achilles 1.8         | OMOP CDM characterization analyses   |
| `achilles-export`| Achilles 1.8         | Export results to JSON for AresIndexer |
| `dqd`            | DataQualityDashboard | Data quality checks (CDMv5.4 rules)  |
| `cdmonboarding`  | CdmOnboarding        | Onboarding report (incl. DQD input)  |

All three OHDSI packages are **vendored** as tarballs under `vendor/` because corporate proxies (APHM) block GitHub. The PostgreSQL JDBC driver is vendored under `drivers/`.

## Build

### No proxy

```bash
docker compose -f ohdsi-tools/docker-compose.yml build
```

### Behind APHM proxy (cntlm on localhost:3128)

```bash
docker compose -f ohdsi-tools/docker-compose.yml build \
  --build-arg HTTP_PROXY=http://localhost:3128 \
  --build-arg HTTPS_PROXY=http://localhost:3128 \
  --build-arg PROXY_CA_HOST=10.61.131.6 \
  --build-arg PROXY_CA_PORT=3128
```

`PROXY_CA_HOST` / `PROXY_CA_PORT` trigger the MITM-CA extraction step (only needed if the proxy intercepts SSL).

## How OPAL uses these images

The services are **never** brought up with `docker compose up`. OPAL's backend launches them on-demand via the Docker SDK — see [backend/modules/ohdsi/router.py](../backend/modules/ohdsi/router.py).

Image naming is controlled by `OHDSI_IMAGE_PREFIX` (default `ohdsi-docker`). The `image:` field in [docker-compose.yml](docker-compose.yml) hard-codes the same prefix so the backend finds the images without config changes.

Per-CDM DB credentials are injected as env vars at launch (overriding `.env`). The `.env` here only provides static defaults (driver path, schema names, CDM version).

## Layout

```
ohdsi-tools/
├── Dockerfile               R 4.3.2 + OHDSI packages
├── docker-compose.yml       Build definitions + runtime contract
├── .env.example             Template for static config
├── drivers/
│   └── postgresql-42.7.4.jar    JDBC driver
├── scripts/
│   ├── config/                  DQD CDMv5.4 rule sets
│   ├── run_achilles.R
│   ├── run_achilles_export.R
│   ├── run_dqd.R
│   └── run_cdmonboarding.R
└── vendor/                      OHDSI R package tarballs
    ├── Achilles.tar.gz
    ├── DataQualityDashboard.tar.gz
    └── CdmOnboarding.tar.gz
```

## Outputs

Each run writes to `output/<service>/<cdm_name>/` (the per-CDM sub-folder is created by OPAL — see `ensure_cdm_output_dirs()` in the router). The frontend reads/serves these via `/api/ohdsi/files/`.
