# OPAL — Round 2 Audit Report

> Date: 2026-03-15
> Scope: Remaining bugs, missing features, architectural issues, code quality problems
> Basis: Cross-referenced against PLAN_AMELIORATION.md (Round 1, 2026-03-13)

Items marked **[V2]** were identified in the previous PLAN_AMELIORATION.md but remain unfixed.

---

## 1. SECURITY

### 1.1 [P0] Path traversal in OHDSI file browser

**File:** `backend/modules/ohdsi/router.py:284-295`
**Issue:** The `/files/{path:path}` endpoint joins user-supplied `path` to `output_dir` without validating the result stays within the allowed directory. An attacker can use `../` sequences to read arbitrary files on the server (e.g., `/api/ohdsi/files/../../etc/passwd`).
**Proposed fix:**
```python
target = (output_dir / path).resolve()
if not str(target).startswith(str(output_dir.resolve())):
    raise HTTPException(status_code=403, detail="Access denied")
```

---

### 1.2 [P1] OHDSI containers run with `network_mode="host"`

**File:** `backend/modules/ohdsi/router.py:126`
**Issue:** Docker containers launched by the OHDSI module use `network_mode="host"`, giving them access to the host network stack, including localhost services, cloud metadata endpoints, and internal networks.
**Proposed fix:** Create a dedicated Docker network and attach containers to it. Pass CDM connection info through environment variables so they can reach the database without host networking.

---

### 1.3 [P1] Notification creation endpoint lacks authentication

**File:** `backend/modules/notifications_router.py:179-192`
**Issue:** The `POST /api/notifications/create` endpoint has no authentication or authorization dependency. Any unauthenticated caller can create notifications for any user, enabling spam or phishing-style notifications.
**Proposed fix:** Add an authentication dependency (e.g., `Depends(_require_manage_access)` or a dedicated admin check) or restrict this endpoint to internal use only (not routed publicly).

---

### 1.4 [P1] SQL injection via f-string in concept_set/router.py

**File:** `backend/modules/concept_set/router.py:167-170, 202-208`
**Issue:** The `resolve` and `counts` endpoints use f-strings to interpolate `omop_schema`, table names, and column names into SQL. While `omop_schema` comes from server config and `DOMAIN_CONFIG` is server-controlled, the pattern is inconsistent with the safe `psycopg2.sql` approach used in `concept/router.py` (which was fixed in Round 1). The `placeholders` on line 167 uses `str(int(i))` which provides minimal protection but is not parameterized.
**Proposed fix:** Refactor to use `psycopg2.sql.SQL` and `psycopg2.sql.Identifier` consistently, matching the pattern in `concept/router.py`.

---

### 1.5 [P1] SQL f-strings in estimation/router.py

**File:** `backend/modules/estimation/router.py:107-192`
**Issue:** The `_build_km_sql` function constructs SQL entirely via f-strings with `omop_schema`, `domain_table`, `date_col`, and other column names interpolated directly. While these values derive from server-side config, this is inconsistent with the safe SQL composition pattern established elsewhere.
**Proposed fix:** Use `psycopg2.sql.SQL` and `psycopg2.sql.Identifier` for all table/column/schema references.

---

### 1.6 [P1] SQL f-strings in search_router.py

**File:** `backend/modules/search_router.py:117-136`
**Issue:** Source value search uses f-strings with `schema`, `table`, `source_col`, and `source_name_col` from `DOMAIN_CONFIG`. Same inconsistency as above.
**Proposed fix:** Use `psycopg2.sql` module consistently.

---

### 1.7 [P2] nginx static asset location overrides security headers

**File:** `frontend/nginx.conf:28-32`
**Issue:** The nested `location ~* \.(js|css|svg|woff2?|ttf|eot|ico)$` block uses `add_header Cache-Control ...` which, per nginx behavior, **replaces all parent-level `add_header` directives**. Static assets are served without CSP, HSTS, X-Content-Type-Options, X-Frame-Options, or any other security header.
**Proposed fix:** Repeat all security headers in the static asset location block, or use the `more_set_headers` directive from the nginx headers-more module which appends instead of replaces.

---

## 2. MISSING API VALIDATIONS

### 2.1 [P1] Cohort criteria typed as raw `dict`

**File:** `backend/modules/cohort/router.py:46, 52, 57`
**Issue:** `CohortCreateRequest.criteria`, `CohortUpdateRequest.criteria`, and `CohortCountRequest.criteria` are all typed as bare `dict`. This provides zero Pydantic validation on the most important field in the cohort module. Malformed criteria will only be caught later during SQL building, producing unhelpful errors.
**Proposed fix:** Define a `CohortCriteria` Pydantic model (with `groups`, `logical_operator`, etc.) matching the structure expected by `sql_builder.py`. Use `CohortCriteria` instead of `dict`.

---

### 2.2 [P1] `concept_set_counts` uses `body: dict`

**File:** `backend/modules/concept_set/router.py:182`
**Issue:** The endpoint accepts `body: dict` instead of a Pydantic model. No validation on the request body.
**Proposed fix:** Create a `ConceptSetCountsRequest(BaseModel)` with `cdm_name: str = Field(...)`.

---

### 2.3 [P1] `assign_role` uses `body: dict`

**File:** `backend/main.py:469`
**Issue:** The admin role assignment endpoint uses `body: dict` instead of a Pydantic model.
**Proposed fix:** Create `AssignRoleRequest(BaseModel)` with `role: str = Field(..., min_length=1)`.

---

### 2.4 [P2] `submit_access_request` uses `body: dict`

**File:** `backend/main.py:597`
**Issue:** The access request endpoint uses `body: dict` with manual field validation instead of Pydantic.
**Proposed fix:** Create `AccessRequestSubmission(BaseModel)` with `username: str`, `requested_role: str`, `email: str = ""`, etc.

---

### 2.5 [P2] `add_user_direct` uses raw `request.json()`

**File:** `backend/main.py:775-779`
**Issue:** The admin user-add endpoint bypasses Pydantic entirely by reading `request.json()` directly, then doing manual validation.
**Proposed fix:** Define a Pydantic model and use it as a parameter.

---

## 3. INCOMPLETE CRUD OPERATIONS

### 3.1 [P2] No DELETE endpoint for IncidenceAnalysis

**File:** `backend/modules/incidence/router.py`
**Issue:** The incidence module has create (POST `/save`), list (GET `/`), and get (GET `/{id}`) endpoints, but no delete endpoint. Users cannot remove saved incidence analyses.
**Proposed fix:** Add `DELETE /api/incidence/{analysis_id}` endpoint.

---

### 3.2 [P2] No DELETE endpoint for EstimationAnalysis

**File:** `backend/modules/estimation/router.py`
**Issue:** Same as above for the estimation module.
**Proposed fix:** Add `DELETE /api/estimation/{analysis_id}` endpoint.

---

### 3.3 [P2] No UPDATE endpoint for CohortTemplate

**File:** `backend/modules/cohort_templates_router.py`
**Issue:** The template module has create and delete but no update/PUT endpoint. Custom templates cannot be edited after creation.
**Proposed fix:** Add `PUT /api/cohort-templates/{template_id}` endpoint.

---

## 4. DEAD CODE & UNUSED IMPORTS

### 4.1 [P3] LandingPage is dead code

**File:** `frontend/src/pages/LandingPage.tsx` (entire file)
**Issue:** `LandingPage.tsx` exists but is never imported in `App.tsx` and is not routed. It uses `framer-motion` which is an extra dependency serving no purpose.
**Proposed fix:** Remove `LandingPage.tsx` and the `framer-motion` dependency if unused elsewhere.

---

## 5. FRONTEND/BACKEND CONTRACT MISMATCHES

### 5.1 [P2] `MappingSuggestion.source` type missing variants

**File:** `frontend/src/types/index.ts:666`
**Issue:** The `source` field is typed as `'exact' | 'relationship' | 'fuzzy' | 'contextual'` but the backend also produces `'sapbert'` and `'keyword'` sources (6 strategies total per CLAUDE.md). The frontend type is incomplete.
**Proposed fix:** Update to `'exact' | 'relationship' | 'fuzzy' | 'contextual' | 'sapbert' | 'keyword'`.

---

## 6. DEPRECATED API USAGE

### 6.1 [P2] `datetime.utcnow()` used in multiple files

**Files:**
- `backend/modules/quality/router.py:77`
- `backend/modules/quality/report_builder.py:122, 376`
- `backend/modules/mapping/router.py:1134, 1212`
- `backend/modules/cohort/router.py:453, 1166, 1174, 1211`

**Issue:** `datetime.utcnow()` is deprecated since Python 3.12. It returns a naive datetime which can cause issues with timezone-aware comparisons.
**Proposed fix:** Replace all occurrences with `datetime.now(timezone.utc)` (from `datetime import timezone`).

---

## 7. DATABASE SCHEMA ISSUES

### 7.1 [P2] No ForeignKey constraints between tables

**File:** `backend/db/models.py`
**Issue:** The 20+ models use no `ForeignKey` constraints. For example, `CdmAccess.cdm_name` has no FK to `CdmConfig.name`, `CohortVersion.cohort_id` has no FK to `Cohort.id`, etc. This means the database cannot enforce referential integrity, and orphaned records can silently accumulate (the cascade delete in `cdm_router.py:222-258` is a manual workaround for this).
**Proposed fix:** Add ForeignKey constraints with appropriate ON DELETE behavior (CASCADE or SET NULL). This requires an Alembic migration.

---

## 8. PERFORMANCE

### 8.1 [P2] [V2] `admin_cohorts_by_user` loads ALL CohortShares

**File:** `backend/modules/cohort_sharing_router.py:177`
**Issue:** `db.query(CohortShare).all()` loads every share record into memory. This was identified in PLAN_AMELIORATION.md item 2.2 but remains unfixed in this specific location (the `cdm_access_router.py` N+1 was fixed but not this one).
**Proposed fix:** Filter shares by the cohort IDs already loaded, or use a single JOIN query.

---

### 8.2 [P2] [V2] Pagination missing on multiple endpoints

**Files:**
- `backend/modules/cdm_router.py:124` (list CDMs)
- `backend/modules/cohort_templates_router.py:192` (list templates)
- `backend/modules/groups_router.py` (list groups)
- `backend/modules/saved_queries_router.py` (list queries)
- `backend/modules/favorites_router.py` (list favorites)

**Issue:** These endpoints return `.all()` without any limit. Identified in PLAN_AMELIORATION.md item 2.5 but not implemented.
**Proposed fix:** Add `skip: int = 0, limit: int = 100` query parameters and return `{ items: [...], total: int }`.

---

### 8.3 [P3] `_ensure_builtins` runs on every template list request

**File:** `backend/modules/cohort_templates_router.py:188`
**Issue:** `_ensure_builtins(db)` is called on every `GET /api/cohort-templates/` request. It queries and potentially inserts built-in templates each time.
**Proposed fix:** Use an application-level flag or check once at startup instead of on every request.

---

## 9. HARDCODED VALUES

### 9.1 [P2] Hardcoded French notification messages in backend

**Files:**
- `backend/modules/quality/router.py:133-134` -- `"Analyse terminee : {domain}"`, `"L'analyse qualite de..."`
- `backend/modules/cohort_sharing_router.py:107` (likely similar French strings)
- `backend/main.py:615` -- `"Une demande est deja en cours pour ce matricule"`
- `backend/main.py:784` -- `"Matricule requis"`, `"Role invalide"`

**Issue:** Backend notification titles and error messages are hardcoded in French. The backend has an i18n system (`i18n/en.json`, `i18n/fr.json`) but it is not used for these messages. Users with English locale will see French notifications.
**Proposed fix:** Use the backend i18n system or return translation keys that the frontend resolves.

---

### 9.2 [P3] Hardcoded English strings in HomePage.tsx

**File:** `frontend/src/pages/HomePage.tsx`
**Issue:** Several UI strings are hardcoded in English instead of using the i18n system: "Notifications" (title), "No notifications", "persons", etc.
**Proposed fix:** Replace with `t('key')` calls using react-i18next.

---

## 10. TYPESCRIPT TYPE SAFETY

### 10.1 [P2] [V2] Widespread `any` types in API client

**File:** `frontend/src/api/client.ts` (lines 402, 406, 410, 414, 525, 572, 625, 643, 659, 669, 681 and more)
**Issue:** Many API response types use `any`, negating TypeScript's type checking benefits. Identified in PLAN_AMELIORATION.md item 3.5 but not addressed.
**Proposed fix:** Replace `any` with concrete types from `types/index.ts` or at minimum `unknown`. Enable `@typescript-eslint/no-explicit-any` ESLint rule.

---

### 10.2 [P3] [V2] Empty `.catch(() => {})` blocks throughout frontend

**Files:** `QualityPage.tsx`, `CohortPage.tsx`, `MappingPage.tsx`, `App.tsx:132`
**Issue:** Silent error swallowing. Identified in PLAN_AMELIORATION.md item 3.6 but not fixed.
**Proposed fix:** At minimum `.catch(console.error)`, ideally show toast notifications.

---

## 11. ACCESSIBILITY (a11y)

### 11.1 [P1] [V2] No ARIA attributes in custom UI components

**Issue:** Identified in PLAN_AMELIORATION.md item 7.1. Custom components (Button, Input, Select, Modal, Table, Spinner) still lack `aria-label`, `aria-describedby`, `role`, `aria-expanded`, `aria-live` attributes.
**Proposed fix:** See PLAN_AMELIORATION.md item 7.1 for the full list.

---

### 11.2 [P2] [V2] Keyboard navigation incomplete

**Issue:** Identified in PLAN_AMELIORATION.md item 7.2. No focus trap in modals, no skip-to-content link.
**Proposed fix:** See PLAN_AMELIORATION.md item 7.2.

---

## 12. MISSING TEST COVERAGE

### 12.1 [P1] [V2] No frontend tests

**Issue:** Zero test files on the frontend. No test framework installed. Identified as P0 in PLAN_AMELIORATION.md item 5.1.
**Proposed fix:** Install Vitest + React Testing Library. Priority tests: API client interceptors, routing, critical pages.

---

### 12.2 [P1] [V2] No CI/CD pipeline

**Issue:** Identified in PLAN_AMELIORATION.md item 5.3. No `.github/workflows` or equivalent.
**Proposed fix:** See PLAN_AMELIORATION.md item 5.3.

---

## 13. ARCHITECTURE

### 13.1 [P1] [V2] No database migration system (Alembic)

**Issue:** Identified in PLAN_AMELIORATION.md item 4.1. Schema changes require manual recreation. No migration history.
**Proposed fix:** Install and configure Alembic with initial migration.

---

### 13.2 [P2] [V2] No optimistic locking for concurrent edits

**Issue:** Identified in PLAN_AMELIORATION.md item 4.3. Two users editing the same cohort or mapping can silently overwrite each other.
**Proposed fix:** Add `version` counter field on Cohort and MappingDecision models, reject updates with stale version (HTTP 409).

---

### 13.3 [P2] [V2] `config.py` uses raw `os.getenv` without validation

**File:** `backend/config.py`
**Issue:** Identified in PLAN_AMELIORATION.md item 4.4. No type validation, no range validation (e.g., `POOL_MIN <= POOL_MAX`).
**Proposed fix:** Migrate to `pydantic.BaseSettings`.

---

### 13.4 [P2] [V2] Synchronous Keycloak HTTP calls block FastAPI

**File:** `backend/main.py:417-440, 532-565`
**Issue:** Identified in PLAN_AMELIORATION.md item 2.6. `requests.get()` calls block the event loop.
**Proposed fix:** Use `httpx.AsyncClient` with `async def` endpoints.

---

### 13.5 [P2] [V2] Large monolithic page components

**Files:**
- `frontend/src/pages/MappingPage.tsx` (~60KB)
- `frontend/src/pages/CohortPage.tsx` (~1000+ lines)
- `frontend/src/pages/QualityPage.tsx` (~800 lines)

**Issue:** Identified in PLAN_AMELIORATION.md item 3.2. Single-file components that are hard to maintain and test.
**Proposed fix:** Extract into sub-components.

---

## 14. DOCKER/DEPLOYMENT

### 14.1 [P2] [V2] No pre-commit hooks

**Issue:** Identified in PLAN_AMELIORATION.md item 6.6. No automated code quality checks before commit.
**Proposed fix:** Install pre-commit with ruff, detect-secrets, etc.

---

### 14.2 [P2] [V2] No Makefile or automation scripts

**Issue:** Identified in PLAN_AMELIORATION.md item 6.4. All operations are manual.
**Proposed fix:** Create a Makefile with dev, test, build, lint targets.

---

### 14.3 [P3] [V2] Backend dependency versions not pinned

**File:** `backend/requirements.txt`
**Issue:** Identified in PLAN_AMELIORATION.md item 6.7. Uses `>=` for all dependencies.
**Proposed fix:** Use `pip-compile` to generate exact pinned versions.

---

## SUMMARY BY PRIORITY

| Priority | Count | V2 (unfixed from Round 1) |
|----------|-------|---------------------------|
| **P0** | 1 | 0 |
| **P1** | 10 | 4 |
| **P2** | 18 | 10 |
| **P3** | 5 | 2 |
| **Total** | **34** | **16** |

### What was FIXED from Round 1 (PLAN_AMELIORATION.md)

These items from the original plan have been successfully addressed:

1. **1.1** SQL injection in concept/router.py -- FIXED (uses `psycopg2.sql` throughout)
2. **1.2** Rate limiting -- FIXED (slowapi installed and configured)
3. **1.3** XSS via i18next `escapeValue: false` -- FIXED (set to `true`)
4. **1.4** CSP headers -- FIXED (added in nginx.conf)
5. **1.7** Keycloak running as root -- FIXED (`user: "0:0"` removed)
6. **1.8** CORS too permissive -- FIXED (restricted)
7. **2.1** ConnectionError handler -- FIXED (exception handler added)
8. **2.2** N+1 in cdm_access_router.py -- FIXED (uses subquery)
9. **4.2** No cascade delete for CDMs -- FIXED (explicit cascade in delete endpoint)
10. **6.1** Hardcoded hostnames in docker-compose -- FIXED (uses env vars)
11. **6.2** No Docker resource limits -- FIXED (deploy limits added)
12. **6.5** No Keycloak healthcheck -- FIXED (healthchecks on all services)

### Recommended Execution Order

**Immediate (P0-P1 security):**
1. Path traversal fix (1.1)
2. Notification auth check (1.3)
3. Consistent SQL composition in concept_set, estimation, search routers (1.4-1.6)
4. OHDSI network_mode fix (1.2)

**Short-term (API quality + CRUD gaps):**
5. Replace `dict` bodies with Pydantic models (2.1-2.5)
6. Add missing DELETE endpoints (3.1-3.2)
7. Add missing UPDATE endpoint for templates (3.3)
8. Fix nginx header inheritance (1.7)

**Medium-term (V2 backlog):**
9. Alembic migrations (13.1)
10. Frontend tests (12.1)
11. CI/CD pipeline (12.2)
12. Pagination on list endpoints (8.2)
13. `any` type cleanup (10.1)
14. ARIA accessibility (11.1)

---

*This report is based on a complete code audit as of 2026-03-15, cross-referenced against PLAN_AMELIORATION.md from 2026-03-13.*
