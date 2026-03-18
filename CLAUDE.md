# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OPAL (OMOP Platform for Analytics & Lineage) is a full-stack web application for analyzing OMOP CDM (Common Data Model) databases. It provides data quality analysis, cohort building, vocabulary mapping, and concept exploration. The application connects read-only to external OMOP CDM PostgreSQL databases while storing all application state in its own internal PostgreSQL database.

## Commands

### Full Stack (Docker Compose)
```bash
export SECRET_KEY=$(openssl rand -hex 32)
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
# Backend (601 tests)
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

**Configuration**: `config.py` — All settings via environment variables. Key vars: `DATABASE_URL`, `SECRET_KEY`, `AUTH_ENABLED`, `KEYCLOAK_URL`, `KEYCLOAK_ISSUER_URL`, `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`, `CORS_ORIGINS`. Contains `DOMAIN_CONFIG` dict mapping OMOP domains to their table/column names. See `.env.example` for full reference.

**Database layer** (`db/`):
- `app_db.py` — SQLAlchemy engine/session for the internal app database (pool_size, max_overflow, pool_recycle configurable via env vars)
- `models.py` — 22 models with composite indexes on frequently-filtered columns: `AnalysisSnapshot(cdm_name, domain, version)`, `CohortVersion(cohort_id, version)`, `MappingDecision(cdm_name, domain, source_value)`, `Notification(username, read)`, `NotificationPreference(username, type)`
- `omop_connector.py` — Per-CDM `ThreadedConnectionPool` for external OMOP CDM connections. `PooledConnection` wrapper makes `close()` return to pool transparently. Pools auto-evicted after 30min idle, invalidated on CDM update/delete.

**Modules** (`modules/`) — 19 routers:
- `admin_router.py` — User management, access requests (`/api/admin/`)
- `cdm_router.py` — CDM registration CRUD, connection testing, settings management (`/api/cdm/`)
- `quality/router.py` + `quality/engine.py` — Quality analysis with Achilles-like metrics, snapshot versioning, comparison, CSV export (`/api/quality/`)
- `cohort/router.py` + `cohort/sql_builder.py` + `cohort/pathways.py` — Visual cohort builder, JSON criteria → SQL generation, attrition analysis, pathways analysis (`/api/cohorts/`)
- `mapping/router.py` + `mapping/suggest.py` — Mapping workflow with 6 suggestion strategies (SapBERT, exact, relationship, keyword, fuzzy, contextual), audit trail (`/api/mapping/`)
- `concept/router.py` — Concept search, hierarchy navigation, source value lookup, TTL cache (`/api/concepts/`)
- `ohdsi/router.py` — OHDSI Docker container orchestration (`/api/ohdsi/`)
- `concept_set/router.py` — Concept set CRUD (`/api/concept-sets/`)
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

**Security**:
- `utils/crypto.py` — Fernet encryption for stored CDM passwords using `SECRET_KEY`
- `utils/sql_safety.py` — SQL identifier validation (`safe_identifier()`)
- `utils/csv_safety.py` — CSV formula injection protection
- `utils/rate_limit.py` — Rate limiting decorator (slowapi)
- `utils/ws_manager.py` — WebSocket connection manager for real-time notifications
- `utils/cdm_helper.py` — Centralized CDM connection helper with safe_identifier

**i18n**: `i18n/en.json` and `i18n/fr.json` — Translations cached at module load time (not read per-request). Served via `/api/i18n/{lang}`.

### Frontend (`frontend/`)

**Stack**: React 18 + TypeScript + Vite + Custom Neumorphic UI components + Framer Motion + Recharts + Lucide icons

**Entry**: `src/main.tsx` → `src/App.tsx` — React Router with sidebar layout. Selected CDM stored in `localStorage` and passed as prop to all pages.

**API client**: `src/api/client.ts` — Axios-based client organized by module (`cdmApi`, `qualityApi`, `cohortApi`, `mappingApi`, `conceptApi`). All requests go to `/api` prefix.

**Pages** (`src/pages/`): `HomePage`, `QualityPage`, `CohortPage`, `DataManagementPage`, `MappingPage`, `CdmManagementPage`, `SettingsPage`, `ConceptExplorerPage`, `OhdsiPage`, `AuditPage`, `UserManagementPage`, `LoginPage`, `IncidencePage`, `EstimationPage`, `ConceptSetPage`

**UI Components** (`src/components/ui/`): Neumorphic design system + `AnimatedList` (Framer Motion animations), `SkeletonPatterns` (contextual loaders), `ErrorState` (5 error variants), `Empty` (11 empty state variants), `Toast` (animated notifications)

**Hooks**: `useTheme` (dark/light toggle), `useNotificationWs` (WebSocket real-time), `useNotifDots` (notification badges)

**Types**: `src/types/index.ts` — Shared TypeScript interfaces for all API responses.

### Key Design Decisions

- External CDMs are accessed **read-only** via raw `psycopg2` (not SQLAlchemy). The only write to CDM is optional `source_to_concept_map` updates during mapping apply.
- CDM connections use a **per-CDM `ThreadedConnectionPool`** (min=2, max=20). `PooledConnection` wrapper intercepts `close()` to return to pool. Pools auto-evicted after 30min idle, invalidated on CDM credential update/delete.
- All app state (configs, snapshots, cohorts, mapping decisions) lives in the internal PostgreSQL.
- Quality analysis snapshots are versioned for temporal comparison.
- Cohort criteria use a JSON structure that gets converted to SQL by `sql_builder.py`.
- Mapping suggestions use 6 ranked strategies: SapBERT (pre-computed), exact match, relationship-based, keyword, fuzzy text, contextual.
- Notifications are delivered in **real-time via WebSocket** (zero polling). WebSocket connections are authenticated via one-time SSE tickets.
- The app supports **dark mode** (Emerald Night, default) and **light mode** (Crème Sauge palette). Theme persisted in `localStorage`.
- **Pathways Analysis** implements OHDSI ATLAS-style treatment pathway visualization with interactive sunburst chart.
- All SQL identifiers use `psycopg2.sql.SQL` + `sql.Identifier` — no f-string SQL anywhere.
- Schema migrations managed by **Alembic** (initial migration covers 22 tables).
