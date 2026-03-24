# OPAL Backend Tests

## Quick Start

```bash
cd backend

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=term-missing

# Run a specific test file
pytest tests/test_conformity.py -v

# Run a single test
pytest tests/test_clinical_domain.py::TestGetGlobalStats::test_basic -v
```

## Test Architecture

### Two Testing Strategies

OPAL tests use two complementary strategies depending on the module:

#### 1. App DB Tests (SQLite in-memory)

For endpoints that only use the internal app database (cohorts, sharing, groups, favorites, etc.), tests use `conftest.py` which:
- Overrides `DATABASE_URL` to SQLite in-memory
- Injects a fake auth middleware (`_FakeAuthMiddleware`) that provides a test user
- Creates/drops all tables before/after each test

```python
def test_something(client):
    resp = client.post("/api/cohorts/", json={...})
    assert resp.status_code == 200
```

Use `X-Test-Username` and `X-Test-Roles` headers to control the test user:
```python
resp = client.get("/api/...", headers={
    "X-Test-Username": "other_user",
    "X-Test-Roles": "viewer",
})
```

#### 2. OMOP Mock Tests (psycopg2 mock)

For code that queries external OMOP CDM databases via psycopg2, tests use `tests/omop_mock.py`:

```python
from tests.omop_mock import make_omop_conn

def test_dashboard():
    conn = make_omop_conn([
        {"total": 500},           # 1st execute -> fetchone returns {"total": 500}
        [{"id": 1}, {"id": 2}],   # 2nd execute -> fetchall returns list of dicts
        Exception("timeout"),      # 3rd execute -> raises exception
    ])
    result = run_dashboard_analysis(conn, "omop_cdm")
    assert result["summary"]["total_persons"] == 500
```

For router integration tests that need both app DB and mocked OMOP connections:
```python
@patch("modules.concept.router.get_omop_connection")
@patch("modules.concept.router.decrypt_password")
def test_search(mock_decrypt, mock_get_conn, client, cdm_name):
    mock_decrypt.return_value = "pass"
    conn, cursor = _mock_concept_conn()
    mock_get_conn.return_value = conn
    cursor.fetchall.return_value = [...]
    resp = client.get(f"/api/concepts/search?cdm_name={cdm_name}&q=test")
```

### omop_mock.py Reference

| Component | Description |
|-----------|-------------|
| `make_omop_conn(responses)` | Create a mock psycopg2 connection with pre-configured responses |
| `MockCursor` | Replays responses in order, supports `fetchone()`, `fetchall()`, and exception raising |
| `DictRow` | Dict subclass mimicking psycopg2's DictRow |

Response types:
- `dict` — returned by `fetchone()`
- `list[dict]` — returned by `fetchall()`
- `Exception` — raised on `execute()`

## Test Files

### Unit Tests (no DB needed)

| File | Module Under Test | Coverage Target |
|------|-------------------|-----------------|
| `test_dashboard_domain.py` | `quality/domains/dashboard.py` | UNION ALL stats, sparklines, error recovery |
| `test_person_domain.py` | `quality/domains/person.py` | Demographics, missing columns, NULL handling |
| `test_observation_period_domain.py` | `quality/domains/observation_period.py` | 6 sub-analyses, cap months, empty data |
| `test_clinical_domain.py` | `quality/domains/clinical.py` | 5 helper functions + main orchestrator |
| `test_report_builder.py` | `quality/report_builder.py` | HTML generation, comparison reports, SVG charts |
| `test_extractor.py` | `datamanagement/extractor.py` | SQL builder, identifier validation, CTE generation |
| `test_cdm_helper.py` | `utils/cdm_helper.py` | CDM lookup, auth checks, schema override |
| `test_pathways_analysis.py` | `cohort/pathways.py` | Sunburst tree builder, pruning, percentages |
| `test_conformity.py` | `quality/conformity.py` | Conformity checks, table existence, scoring |
| `test_engine.py` | `quality/engine.py` | Domain config validation |
| `test_comparator.py` | `quality/comparator.py` | Snapshot comparison |
| `test_incidence_engine.py` | `incidence/engine.py` | Incidence rate computation |
| `test_survival.py` | `estimation/survival.py` | Kaplan-Meier, log-rank test |
| `test_crypto.py` | `utils/crypto.py` | Fernet encryption/decryption |
| `test_sql_builder.py` | `cohort/sql_builder.py` | JSON criteria to SQL conversion |
| `test_suggest.py` | `mapping/suggest.py` | Suggestion strategies |

### Integration Tests (app DB)

| File | Module Under Test | What's Tested |
|------|-------------------|---------------|
| `test_api.py` | `cdm_router.py` | CDM CRUD |
| `test_cohort_api.py` | `cohort/router.py` | Cohort CRUD |
| `test_cohort_sharing.py` | `cohort_sharing_router.py` | Sharing, pagination |
| `test_cohort_templates.py` | `cohort_templates_router.py` | Template CRUD |
| `test_mapping_api.py` | `mapping/router.py` | Mapping decisions, dashboard |
| `test_favorites.py` | `favorites_router.py` | Favorites CRUD |
| `test_groups.py` | `groups_router.py` | Group CRUD, role restrictions |
| `test_notifications.py` | `notifications_router.py` | Notification CRUD |
| `test_saved_queries.py` | `saved_queries_router.py` | Query CRUD |
| `test_admin_api.py` | `main.py` (admin endpoints) | Role assignment, user toggle |
| `test_audit_api.py` | `main.py` (audit endpoints) | Audit log reading |
| `test_access_requests.py` | `cdm_access_router.py` | Access request workflow |
| `test_search.py` | `search_router.py` | Global search |
| `test_role_access.py` | Various routers | IDOR protection |
| `test_concept_set_api.py` | `concept_set/router.py` | Concept set CRUD, ownership |
| `test_estimation_router.py` | `estimation/router.py` | Estimation CRUD |
| `test_incidence_router.py` | `incidence/router.py` | Incidence CRUD |
| `test_datamanagement_router.py` | `datamanagement/router.py` | Table listing, extraction status |

### Integration Tests (app DB + OMOP mock)

| File | Module Under Test | What's Tested |
|------|-------------------|---------------|
| `test_concept_router.py` | `concept/router.py` | Search, details, hierarchy, domains |

## Writing New Tests

### Adding a unit test for an OMOP module

1. Identify what queries the function executes (in order)
2. Build response list matching that sequence
3. Use `make_omop_conn()` to create the mock connection

```python
from tests.omop_mock import make_omop_conn

def test_my_analysis():
    responses = [
        {"count": 100},           # Query 1: COUNT(*)
        [{"id": 1, "name": "A"}], # Query 2: SELECT ...
    ]
    conn = make_omop_conn(responses)
    result = my_analysis_function(conn, "omop_cdm")
    assert result["total"] == 100
```

### Adding an integration test for a router

1. Create a CDM fixture if the endpoint needs one
2. Use `@patch` to mock `get_omop_connection` and `decrypt_password`
3. Configure cursor responses

### Common Fixtures

- `client` — FastAPI `TestClient` with fake auth
- `cdm_name` — Creates a test CDM and returns its name
- `setup_db` — Auto-fixture that creates/drops tables per test

## Coverage Targets

| Category | Target | Notes |
|----------|--------|-------|
| Pure functions (engine, survival, sql_builder) | 95%+ | No external deps |
| App DB routers (cohorts, sharing, groups) | 90%+ | Full CRUD tested |
| OMOP analysis modules (clinical, dashboard, person) | 60-80% | Mocked connections |
| OMOP routers (concept, quality, mapping) | 40-60% | Complex query mocking |
| Docker-dependent (OHDSI) | 25% | Cannot test container ops |
| Report builder | 50%+ | HTML output validation |
