"""
FULL multi-engine integration coverage — every endpoint that runs SQL on the
external OMOP CDM, exercised against a *real* database (PostgreSQL or Oracle).

Purpose: prove there are no engine-specific surprises when OPAL connects to a
real CDM. This complements test_integration_omop.py (which deep-checks a subset)
by smoke-covering 100% of the CDM-touching surface: each endpoint/worker must
execute its CDM SQL without an engine error.

Gate: skipped unless OPAL_ITEST_OMOP_HOST is set. Select the engine with
OPAL_ITEST_OMOP_DBTYPE (postgresql|oracle). Seeds:
  - PostgreSQL: tests/fixtures/omop_mini_seed.sql
  - Oracle:     tests/fixtures/omop_mini_seed_oracle.sql

Synchronous endpoints are driven over HTTP (TestClient). Background/async
endpoints (quality analyze/conformity, cohort characterize, mapping
suggest-batch, source-value-cache build, extract) are driven by calling their
worker/engine directly with a real CDM connection — that runs the exact same
CDM SQL, without the threading/polling machinery that the test harness can't
faithfully reproduce.
"""
import os
import pytest

OMOP_HOST = os.environ.get("OPAL_ITEST_OMOP_HOST")
pytestmark = pytest.mark.skipif(
    not OMOP_HOST, reason="real OMOP not configured (set OPAL_ITEST_OMOP_HOST)"
)

DBTYPE = os.environ.get("OPAL_ITEST_OMOP_DBTYPE", "postgresql")
SCHEMA = os.environ.get("OPAL_ITEST_OMOP_SCHEMA", "omop_cdm")
CDM = "itest_full"



# ── fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture
def client():
    from tests.conftest import TestClient, app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _bind_worker_sessions(monkeypatch):
    """Async workers create their own app-DB session via db.app_db.SessionLocal,
    which is bound to the original engine, not the test engine. Rebind it to the
    shared in-memory test DB so worker writes (e.g. the source-value cache) land
    where the HTTP endpoints can see them."""
    import db.app_db as app_db
    from tests.conftest import TestSession
    monkeypatch.setattr(app_db, "SessionLocal", TestSession)
    yield


@pytest.fixture
def cdm(client):
    client.post("/api/cdm/", json={
        "name": CDM,
        "db_type": DBTYPE,
        "db_host": OMOP_HOST,
        "db_port": int(os.environ.get("OPAL_ITEST_OMOP_PORT", "5432")),
        "db_name": os.environ.get("OPAL_ITEST_OMOP_DB", "postgres"),
        "db_user": os.environ.get("OPAL_ITEST_OMOP_USER", "opal"),
        "db_password": os.environ.get("OPAL_ITEST_OMOP_PASSWORD", "x"),
        "omop_schema": SCHEMA,
    })
    return CDM


@pytest.fixture
def raw_conn(cdm):
    """A real CDM connection + schema map (with dialect) for direct worker calls."""
    from tests.conftest import TestSession
    from utils.cdm_helper import get_cdm_connection
    db = TestSession()
    try:
        conn, schema = get_cdm_connection(db, cdm)
        # Defensive: a prior /sql/execute call leaves its pooled psycopg2 conn in
        # read-only mode (a pre-existing, PG-only pooling leak — close() restores
        # statement_timeout but not the read-only session flag, same on main). Clear
        # it so direct-worker tests that need scratch tables aren't poisoned by it.
        try:
            conn.set_session(readonly=False, autocommit=False)
        except Exception:
            pass
        yield conn, schema
        conn.close()
    finally:
        db.close()


def _mk_cohort(client, cdm, name, domain, concepts):
    r = client.post("/api/cohorts/", json={
        "cdm_name": cdm, "name": name,
        "criteria": {
            "inclusion": {"operator": "AND", "criteria": [
                {"domain": domain, "concepts": concepts,
                 "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}}
            ]},
            "exclusion": {"operator": "OR", "criteria": []},
        },
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture
def cohorts(client, cdm):
    """A target (diabetes) and outcome (metformin) cohort saved in the app DB."""
    target = _mk_cohort(client, cdm, "tgt", "Condition", [201826])
    outcome = _mk_cohort(client, cdm, "out", "Drug", [1503297])
    return target, outcome


@pytest.fixture
def concept_set(client, cdm):
    r = client.post("/api/concept-sets/", json={
        "name": "cs", "cdm_name": cdm, "domain": "Drug",
        "concepts": [{"concept_id": 21600744, "include_descendants": True}],
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


# Inclusion criteria reused by cohort SQL endpoints.
CRIT = {
    "inclusion": {"operator": "AND", "criteria": [
        {"domain": "Condition", "concepts": [320128, 201826],
         "temporal": {"type": "any_time"}, "occurrence": {"type": "any", "count": 1}}
    ]},
    "exclusion": {"operator": "OR", "criteria": []},
}


def _ok(r):
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    return r.json()


def _ok_status(r):
    """For endpoints that stream CSV (no JSON body to parse)."""
    assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"


# ── CONCEPT router ──────────────────────────────────────────────────────────
def test_concept_search(client, cdm):
    _ok(client.get(f"/api/concepts/search?cdm_name={cdm}&q=metformin"))

def test_concept_search_filters(client, cdm):
    _ok(client.get(f"/api/concepts/search?cdm_name={cdm}&q=a&domain=Drug&vocabulary=RxNorm&standard_only=true"))

def test_concept_details(client, cdm):
    _ok(client.get(f"/api/concepts/details/1503297?cdm_name={cdm}"))

def test_concept_hierarchy(client, cdm):
    _ok(client.get(f"/api/concepts/hierarchy/1503297?cdm_name={cdm}"))

def test_concept_source_values(client, cdm):
    _ok(client.get(f"/api/concepts/source-values/1503297?cdm_name={cdm}"))

def test_concept_domains(client, cdm):
    _ok(client.get(f"/api/concepts/domains?cdm_name={cdm}"))

def test_concept_vocabularies(client, cdm):
    _ok(client.get(f"/api/concepts/vocabularies?cdm_name={cdm}"))

def test_concept_counts(client, cdm):
    _ok(client.post(f"/api/concepts/counts?cdm_name={cdm}", json={"concept_ids": [320128, 1503297]}))

def test_concept_counts_source(client, cdm):
    _ok(client.post(f"/api/concepts/counts/source?cdm_name={cdm}", json={"concept_ids": [320128, 1503297]}))

def test_concept_source_value_cache_build(raw_conn, cdm):
    # Drives the async cache-populate worker directly (the CDM read path).
    from modules.concept.source_value_cache import populate_domain
    conn, schema = raw_conn
    n = populate_domain(cdm, "Drug", conn, schema)
    assert n >= 1


# ── MAPPING router ──────────────────────────────────────────────────────────
def test_mapping_concept_lookup(client, cdm):
    _ok(client.get(f"/api/mapping/concept-lookup/{cdm}/1503297"))

def test_mapping_suggest(client, cdm):
    _ok(client.post("/api/mapping/suggest", json={
        "cdm_name": cdm, "domain": "Drug", "source_value": "6809", "source_name": "metformine"}))

def test_mapping_suggest_batch_worker(raw_conn):
    from modules.mapping.suggest import suggest_batch
    conn, schema = raw_conn
    res = suggest_batch(conn, [{"source_value": "6809", "source_name": "metformine"}], "Drug", schema)
    assert isinstance(res, list)

def test_mapping_unmapped(client, cdm, raw_conn):
    # Needs a built source-value cache for (cdm, Drug).
    from modules.concept.source_value_cache import populate_domain
    conn, schema = raw_conn
    populate_domain(cdm, "Drug", conn, schema)
    _ok(client.get(f"/api/mapping/unmapped/{cdm}/Drug"))


# ── COHORT router ───────────────────────────────────────────────────────────
def test_cohort_concept_search(client, cdm):
    _ok(client.post("/api/cohorts/concepts/search", json={"cdm_name": cdm, "query": "metformin", "limit": 10}))

def test_cohort_vocabularies(client, cdm):
    _ok(client.get(f"/api/cohorts/concepts/vocabularies?cdm_name={cdm}"))

def test_cohort_count(client, cdm):
    _ok(client.post("/api/cohorts/count", json={"cdm_name": cdm, "criteria": CRIT}))

def test_cohort_count_approx(client, cdm):
    _ok(client.post("/api/cohorts/count/approximate", json={"cdm_name": cdm, "criteria": CRIT}))

def test_cohort_attrition(client, cdm):
    _ok(client.post("/api/cohorts/attrition", json={"cdm_name": cdm, "criteria": CRIT}))

def test_cohort_sample(client, cdm):
    _ok(client.post("/api/cohorts/sample", json={"cdm_name": cdm, "criteria": CRIT, "limit": 5}))

def test_cohort_sample_detailed(client, cdm):
    _ok(client.post("/api/cohorts/sample/detailed", json={"cdm_name": cdm, "criteria": CRIT, "limit": 5}))

def test_cohort_export_direct(client, cdm):
    _ok_status(client.post("/api/cohorts/export/direct", json={"cdm_name": cdm, "criteria": CRIT}))

def test_cohort_sql_schema(client, cdm):
    _ok(client.get(f"/api/cohorts/sql/schema?cdm_name={cdm}"))

def test_cohort_sql_execute(client, cdm):
    _ok(client.post("/api/cohorts/sql/execute", json={
        "cdm_name": cdm, "sql": f"SELECT concept_id, concept_name FROM {SCHEMA}.concept", "limit": 10}))

def test_cohort_sql_export(client, cdm):
    _ok_status(client.post("/api/cohorts/sql/export", json={
        "cdm_name": cdm, "sql": f"SELECT concept_id, concept_name FROM {SCHEMA}.concept", "limit": 10}))

def test_cohort_characterize_worker(raw_conn):
    from modules.cohort.characterization import run_characterization
    conn, schema = raw_conn
    res = run_characterization(conn, CRIT, schema, top_n=10)
    assert isinstance(res, dict)


# ── QUALITY router ──────────────────────────────────────────────────────────
def test_quality_domains(client, cdm):
    _ok(client.get(f"/api/quality/domains?cdm_name={cdm}"))

def test_quality_analyze_all_domains_worker(raw_conn):
    # Drives the analyze / analyze-batch / stream SQL for every available domain.
    from modules.quality.engine import get_available_domains, run_domain_analysis
    conn, schema = raw_conn
    domains = get_available_domains(conn=conn, omop_schema=schema)
    assert domains
    for d in domains:
        res = run_domain_analysis(conn, d, schema)
        assert isinstance(res, dict)

def test_quality_conformity_worker(raw_conn):
    from modules.quality.conformity import run_conformity_checks
    conn, schema = raw_conn
    res = run_conformity_checks(conn, schema)
    assert isinstance(res, dict)


# ── DATAMANAGEMENT router ───────────────────────────────────────────────────
def test_dm_tables(client, cdm):
    _ok(client.get(f"/api/datamanagement/tables?cdm_name={cdm}"))

def test_dm_columns(client, cdm):
    _ok(client.get(f"/api/datamanagement/tables/person/columns?cdm_name={cdm}"))

def test_dm_extract_schema(client, cdm):
    _ok(client.post(f"/api/datamanagement/extract/schema?cdm_name={cdm}", json={
        "table_selections": [{"table": "person", "columns": ["person_id", "year_of_birth"]}]}))

def test_dm_extract_rows_worker(raw_conn):
    # Drives the extract/start row-extraction SQL directly.
    from modules.cohort.sql_builder import build_cohort_sql
    from modules.datamanagement.extractor import build_table_sql
    conn, schema = raw_conn
    cohort_sql = build_cohort_sql(CRIT, schema)
    sql = build_table_sql(cohort_sql, schema, "condition_occurrence",
                          ["condition_occurrence_id", "person_id"], False, False)
    with conn.dialect.dict_cursor(conn) as cur:
        conn.dialect.execute(cur, sql, [])
        cur.fetchall()


# ── ESTIMATION / INCIDENCE routers ──────────────────────────────────────────
def test_incidence_compute(client, cdm, cohorts):
    target, outcome = cohorts
    _ok(client.post("/api/incidence/compute", json={
        "cdm_name": cdm, "target_cohort_id": target, "outcome_cohort_id": outcome}))

def test_estimation_kaplan_meier(client, cdm, cohorts):
    target, outcome = cohorts
    _ok(client.post("/api/estimation/kaplan-meier", json={
        "cdm_name": cdm, "target_cohort_id": target, "outcome_cohort_id": outcome}))


# ── CONCEPT_SET router ──────────────────────────────────────────────────────
def test_concept_set_resolve(client, cdm, concept_set):
    _ok(client.get(f"/api/concept-sets/{concept_set}/resolve?cdm_name={cdm}"))

def test_concept_set_counts(client, cdm, concept_set):
    _ok(client.post(f"/api/concept-sets/{concept_set}/counts", json={"cdm_name": cdm}))
