# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OPAL (OMOP Platform for Analytics & Lineage) is a full-stack web application for analyzing OMOP CDM (Common Data Model) databases. It provides data quality analysis, cohort building, vocabulary mapping, and concept exploration. The application connects read-only to external OMOP CDM PostgreSQL databases while storing all application state in its own internal PostgreSQL database.

## Commands

> **Network**: this environment has direct internet access — **no HTTP proxy is required** for any install or build (`npm install`, `pip install`, `docker compose build`, etc.). Do not pass `HTTP_PROXY`/`HTTPS_PROXY` build-args or `--build-arg` proxy flags.

### Full Stack (Docker Compose)
```bash
export SECRET_KEY=$(openssl rand -hex 32)
export POSTGRES_PASSWORD=yourpassword
docker compose up -d          # Start all services
docker compose down            # Stop all services
```

### Backend Development
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend Development
```bash
cd frontend
npm install
npm run dev       # Dev server on :5173, proxies /api to :8000
npm run build     # Production build via Vite
```

### Testing
```bash
# Backend (53 test files)
cd backend
pytest tests/ -v              # Run all backend tests
pytest tests/test_api.py -v   # Run a single test file
pytest tests/test_api.py::test_function_name -v  # Run a single test

# Frontend (84 tests)
cd frontend
npx vitest run
```
Tests use SQLite in-memory via `conftest.py` which overrides `DATABASE_URL` and the FastAPI `get_db` dependency. OMOP connections are mocked via `tests/omop_mock.py`. No external database needed for tests.

## Architecture

### Service Topology
```
Frontend (React/Nginx :3000)  →  /api proxy  →  Backend (FastAPI :8000)
                                                      ↓
                                          App DB (PostgreSQL :5432)
                                                      ↓
                                     External OMOP CDM (read-only connections)
```

Docker Compose runs four services: `opal-frontend`, `opal-backend`, `opal-db`, `opal-keycloak`. The app DB on port 5434 (host) maps to 5432 inside the container.

### Backend (`backend/`)

**Entry point**: `main.py` — Creates FastAPI app, registers CORS middleware, optional Keycloak auth, and all routers.

**Configuration**: `config.py` — All settings via environment variables. Key vars: `DATABASE_URL`, `SECRET_KEY`, `AUTH_ENABLED` (default: true), `ENVIRONMENT`, `KEYCLOAK_URL`, `KEYCLOAK_ISSUER_URL`, `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`, `CORS_ORIGINS`, `OMOP_STATEMENT_TIMEOUT_MS`, `MAX_WORKER_THREADS`. Contains `DOMAIN_CONFIG` dict mapping 11 OMOP clinical domains to their table/column names. Drug domain includes optional `source_atc` (`drug_source_atc`) for ATC code search. See `.env.example` for full reference.

**Database layer** (`db/`):
- `app_db.py` — SQLAlchemy engine/session for the internal app database (pool_size, max_overflow, pool_recycle configurable via env vars)
- `models.py` — 26 models with composite indexes on frequently-filtered columns: `AnalysisSnapshot(cdm_name, domain, version)`, `CohortVersion(cohort_id, version)`, `MappingDecision(cdm_name, domain, source_value)`, `Notification(username, read)`, `NotificationPreference(username, type)`
- `omop_connector.py` — Per-CDM `ThreadedConnectionPool` for external OMOP CDM connections. `PooledConnection` wrapper makes `close()` return to pool transparently. Pools auto-evicted after 30min idle, invalidated on CDM update/delete.

**Modules** (`modules/`) — 21 routers:
- `admin_router.py` — User management, access requests (`/api/admin/`)
- `cdm_router.py` — CDM registration CRUD, connection testing, settings management (`/api/cdm/`)
- `quality/router.py` + `quality/engine.py` — Quality analysis with Achilles-like metrics, snapshot versioning, comparison, CSV export (`/api/quality/`)
- `cohort/router.py` + `cohort/sql_builder.py` + `cohort/pathways.py` — Visual cohort builder, JSON criteria → SQL generation, attrition analysis, pathways analysis (`/api/cohorts/`)
- `mapping/router.py` + `mapping/suggest.py` — Mapping workflow with 6 suggestion strategies (SapBERT, exact, relationship, keyword, fuzzy, contextual), audit trail (`/api/mapping/`)
- `concept/router.py` + `concept/source_value_cache.py` — Concept search, hierarchy navigation, source value lookup with pre-computed cache, ATC code search (Drug domain), CSV export from cached results (`/api/concepts/`)
- `ohdsi/router.py` — OHDSI tools (`/api/ohdsi/`). The backend is a thin HTTP client of a dedicated runner service (`opal-ohdsi-runner`, see `ohdsi-tools/runner/`) that executes the R tools as subprocesses — **no Docker socket**. Opt-in via `OHDSI_MODE` (off/on) + `OHDSI_RUNNER_TOKEN`, started with the Compose `ohdsi` profile. See `docs/adr/0001-ohdsi-runner-dedie.md`.
- `concept_set/router.py` — Concept set CRUD with dual storage: OMOP concepts and/or source codes. Source code sets integrate with cohort builder as source_code criteria (`/api/concept-sets/`)
- `incidence/router.py` — Incidence rate analysis (`/api/incidence/`)
- `estimation/router.py` — Population-level estimation (`/api/estimation/`)
- `datamanagement/router.py` — Data management and ETL monitoring (`/api/datamanagement/`)
- `cdm_access_router.py` — Per-CDM user/group access control (`/api/cdm-access/`)
- `notifications_router.py` — User notifications + WebSocket real-time (`/api/notifications/`, `/api/ws/notifications`)
- `favorites_router.py` — User favorites (`/api/favorites/`)
- `saved_queries_router.py` — Saved SQL queries (`/api/saved-queries/`)
- `cohort_templates_router.py` — Cohort templates (`/api/cohort-templates/`)
- `search_router.py` — Global search across entities (`/api/search/`)
- `cohort_sharing_router.py` — Cohort sharing between users (`/api/cohorts/`)
- `groups_router.py` — User groups management (`/api/groups/`)
- `lineage/router.py` + `lineage/parser.py` — ETL lineage documentation upload, parsing and visualization (`/api/lineage/`)
- `recent_router.py` — Recent user activity feed (`/api/recent/`)

**Security**:
- `utils/crypto.py` — Fernet encryption for stored CDM passwords using `SECRET_KEY`
- `utils/sql_safety.py` — SQL identifier validation (`safe_identifier()`)
- `utils/csv_safety.py` — CSV formula injection protection
- `utils/rate_limit.py` — Rate limiting decorator (slowapi)
- `utils/ws_manager.py` — WebSocket connection manager for real-time notifications
- `utils/cdm_helper.py` — Centralized CDM connection helper: `get_cdm_connection()` (returns a `SchemaMap`), `build_schema_map()`, `get_domain_config()` (runtime optional column detection for `source_name`, `source_concept_id`, `source_atc`), `check_cdm_access()` for POST body CDM checks. `SchemaMap` subclasses `str` (its value is the default schema, so it behaves like a single schema everywhere it isn't category-aware) and exposes `.schema_for(table)` / `.t(table)` to resolve the right schema per OMOP table category.
- `utils/thread_pool.py` — Bounded ThreadPoolExecutor (`MAX_WORKER_THREADS`) for background tasks

**i18n**: `i18n/en.json` and `i18n/fr.json` — Translations cached at module load time (not read per-request). Served via `/api/i18n/{lang}`.

### Frontend (`frontend/`)

**Stack**: React 18 + TypeScript + Vite + Custom Neumorphic UI components + Framer Motion + Recharts + Lucide icons

**Entry**: `src/main.tsx` → `src/App.tsx` — React Router with TopNav layout. Selected CDM stored in `localStorage` and passed as prop to all pages. ConceptSetPage, IncidencePage and EstimationPage are embedded as tabs within CohortPage.

**API client**: `src/api/client.ts` — Axios-based client organized by module (`cdmApi`, `qualityApi`, `cohortApi`, `mappingApi`, `conceptApi`). All requests go to `/api` prefix.

**Pages** (`src/pages/`): `HomePage`, `QualityPage`, `CohortPage`, `DataManagementPage`, `MappingPage`, `CdmManagementPage`, `SettingsPage`, `ConceptExplorerPage`, `OhdsiPage`, `AuditPage`, `UserManagementPage`, `LoginPage`, `IncidencePage`, `EstimationPage`, `ConceptSetPage`, `LineagePage`

**UI Components** (`src/components/ui/`): Neumorphic design system + `AnimatedList` (Framer Motion animations), `SkeletonPatterns` (contextual loaders), `ErrorState` (5 error variants), `Empty` (11 empty state variants), `Toast` (animated notifications)

**Hooks**: `useTheme` (dark/light toggle), `useNotificationWs` (WebSocket real-time), `useNotifDots` (notification badges)

**Types**: `src/types/index.ts` — Shared TypeScript interfaces for all API responses.

### Standalone bricks (`standalone/`)

Every functional brick is also shipped as a **self-contained Streamlit app** —
pure Python, no Docker, no application database, no Keycloak, no users. One TOML
file (`standalone/config.toml`, modelled on `config.example.toml`) holds the
read-only OMOP connection.

- **Entry points**: `standalone/apps/<brick>.py` (`quality`, `cohort`, `concepts`,
  `concept_sets`, `mapping`, `incidence`, `estimation`, `datamanagement`,
  `lineage`) plus `apps/opal.py` bundling all nine. `standalone/run.py` is a thin
  `streamlit run` launcher.
- **Code reuse, not a fork**: the apps import the *same* analysis engines from
  `backend/modules/**`. Those engines only need psycopg2; the three
  server-bound modules are replaced at import time by
  `standalone/opal_standalone/shims/` (`utils.cdm_helper`,
  `utils.reference_labels`, `db.app_db`) via `opal_standalone/bootstrap.py`. So
  **an engine must stay free of FastAPI/SQLAlchemy imports at module level** —
  `standalone/tests/test_bootstrap.py` asserts this.
- **Router-level glue** (dated cohort SQL, Kaplan-Meier SQL, concept/vocabulary
  queries, unmapped terms, read-only SQL guard, criteria validation) is
  reimplemented in `opal_standalone/glue.py`; keep it aligned with the routers.
- **Persistence**: SQLite (`opal_standalone/store.py`) replaces the app DB —
  snapshots, cohorts, concept sets, mapping decisions, incidence/estimation
  analyses, lineage graphs. No ownership columns.
- **Out of scope by design**: auth/roles, sharing, groups, notifications,
  favorites, audit, OHDSI R tools, cohort-LLM, and SapBERT suggestions (mapping
  keeps its three deterministic strategies).
- **Tests**: `python -m pytest standalone/tests -q` (66 tests, no database —
  includes Streamlit `AppTest` runs of every brick).

### Key Design Decisions

- External CDMs are accessed **read-only** via raw `psycopg2` (not SQLAlchemy). The only write to CDM is optional `source_to_concept_map` updates during mapping apply.
- **Per-category schemas**: OMOP tables are grouped into the official CDM v5.4 categories (`clinical`, `health_system`, `health_economics`, `derived`, `metadata`, `vocabulary` — see `config.OMOP_TABLE_CATEGORIES` / `TABLE_CATEGORY`). A CDM may store each category in a different PostgreSQL schema via the optional `schema_categories` JSON column on `CdmConfig`/`AnalysisSettings` (settings override config); categories without an entry fall back to `omop_schema`. Every `schema.table` reference across the app resolves through a `SchemaMap` (`.t(table)` in f-strings, `.schema_for(table)` for `psycopg2.sql.Identifier`), so e.g. vocabulary tables can live in a shared schema. The frontend exposes one default-schema field plus a collapsible per-category override section (`SchemaCategoriesEditor`); `GET /api/cdm/categories` returns the category→tables map.
- CDM connections use a **per-CDM `ThreadedConnectionPool`** (min=2, max=20). `PooledConnection` wrapper intercepts `close()` to return to pool. Pools auto-evicted after 30min idle, invalidated on CDM credential update/delete.
- All app state (configs, snapshots, cohorts, mapping decisions) lives in the internal PostgreSQL.
- Quality analysis snapshots are versioned for temporal comparison.
- Cohort criteria use a JSON structure that gets converted to SQL by `sql_builder.py`.
- Mapping suggestions use 3 internal strategies + SapBERT: exact match, relationship-based, ingredient/DCI. SapBERT runs in the dedicated **opal-sapbert** service (multilingual XLM-R `SapBERT-UMLS-2020AB-all-lang-from-XLMR`, baked into the image) — an **independent module, ON by default** (`SAPBERT_MODE`, orthogonal to `COHORT_LLM_MODE`) that is the **shared embedder for BOTH mapping and the cohort-llm RAG** (one model in VRAM). Mapping reads pre-computed top-K from the `sapbert_mappings` table (the runner is only called at *build* time, never at suggestion time), so when SapBERT is off the 3 other strategies still run. The cohort-llm RAG calls the runner's `POST /encode` live; when SapBERT is off, criteria extraction still works but concept-sets are not auto-filled. Returns `warnings` array when CDM columns are missing. Mapping search includes ATC codes for Drug domain.
- Notifications are delivered in **real-time via WebSocket** (zero polling). WebSocket connections are authenticated via one-time SSE tickets.
- The app supports **dark mode** (Emerald Night, default) and **light mode** (Crème Sauge palette). Theme persisted in `localStorage`.
- **Pathways Analysis** implements OHDSI ATLAS-style treatment pathway visualization with interactive sunburst chart.
- All SQL identifiers validated via `safe_identifier()` (63-char limit). Most modules use `psycopg2.sql.SQL` + `sql.Identifier`; cohort `sql_builder.py` and `pathways.py` use f-strings with defense-in-depth (`safe_identifier()` + `int()` casts + date regex).
- **Source value cache** (`SourceValueCache` model) pre-computes distinct source values with counts per CDM/domain into the app DB. Includes `source_atc` column for Drug domain ATC codes. Cache is used by concept search, cohort builder autocomplete, mapping explorer, and CSV exports. Populated via SSE endpoint with progress tracking.
- **Concept sets** store both OMOP concepts (`concepts` array) and source codes (`source_codes` array) in `concepts_json`. When added to cohort builder, source code sets create `source_codes`-based criteria (match by `source_value`), while concept sets create `concepts`-based criteria (match by `concept_id`). CriteriaPanel auto-refreshes via `opal:concept-sets-changed` custom event.
- **ATC code support**: Drug domain config includes optional `source_atc` column (`drug_source_atc`). Searched in concept explorer (restricted to Drug domain via `and_` clause), cohort SQL builder, mapping explorer, and source value cache. `get_domain_config()` strips the column if absent from the CDM.
- **ETL Lineage** visualization: HTML ETL documentation is uploaded, parsed into a graph of source/target tables with transformations, and rendered as an interactive lineage diagram.
- Schema migrations managed by **Alembic** (initial migration covers 26 models).
