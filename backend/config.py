"""
OPAL — Configuration.

All settings are loaded from environment variables with sensible defaults.
"""
import logging
import os
from pathlib import Path

_logger = logging.getLogger(__name__)

# Paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Security
SECRET_KEY = os.getenv("SECRET_KEY", "")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Application database
DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    if ENVIRONMENT == "production":
        raise RuntimeError(
            "FATAL: DATABASE_URL is not set. "
            "Set a DATABASE_URL environment variable for production."
        )
    DATABASE_URL = "postgresql://opal:opal@opal-db:5432/opal"
    _logger.warning("DATABASE_URL not set — using default dev credentials")

_INSECURE_KEYS = {"", "change-me-in-production"}
if SECRET_KEY in _INSECURE_KEYS:
    if ENVIRONMENT == "production":
        raise RuntimeError(
            "FATAL: SECRET_KEY is not set or uses the insecure default. "
            "Set a strong SECRET_KEY environment variable for production. "
            "Generate one with: openssl rand -hex 32"
        )
    _logger.warning(
        "SECRET_KEY is not set or uses the insecure default. "
        "Set a strong SECRET_KEY environment variable for production. "
        "Generate one with: openssl rand -hex 32"
    )
    if not SECRET_KEY:
        SECRET_KEY = "change-me-in-production"
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").lower() == "true"

if ENVIRONMENT == "production" and not AUTH_ENABLED:
    raise RuntimeError(
        "FATAL: AUTH_ENABLED=false is not allowed in production. "
        "Set AUTH_ENABLED=true or ENVIRONMENT=development."
    )
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://keycloak:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "opal")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "opal-frontend")
# Public URL of Keycloak (as seen by browsers) — used to verify JWT issuer.
# Defaults to KEYCLOAK_URL if not set (works when backend and browsers use the same URL).
KEYCLOAK_ISSUER_URL = os.getenv("KEYCLOAK_ISSUER_URL", KEYCLOAK_URL)

# CORS
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")

# OMOP connection pool
OMOP_POOL_MIN_CONN = int(os.getenv("OMOP_POOL_MIN_CONN", "2"))
OMOP_POOL_MAX_CONN = int(os.getenv("OMOP_POOL_MAX_CONN", "20"))
OMOP_POOL_IDLE_TIMEOUT = int(os.getenv("OMOP_POOL_IDLE_TIMEOUT", "1800"))
OMOP_STATEMENT_TIMEOUT_MS = int(os.getenv("OMOP_STATEMENT_TIMEOUT_MS", "1800000"))

# Bounded thread pool for background tasks (quality, mapping, extraction)
MAX_WORKER_THREADS = int(os.getenv("MAX_WORKER_THREADS", "16"))

# App DB pool (SQLAlchemy)
APP_DB_POOL_SIZE = int(os.getenv("APP_DB_POOL_SIZE", "10"))
APP_DB_MAX_OVERFLOW = int(os.getenv("APP_DB_MAX_OVERFLOW", "20"))
APP_DB_POOL_RECYCLE = int(os.getenv("APP_DB_POOL_RECYCLE", "1800"))

# OMOP defaults
DEFAULT_OMOP_SCHEMA = "omop_cdm"
DEFAULT_TOP_UNMAPPED_TERMS = 50
DEFAULT_TOP_CONCEPTS = 50
DEFAULT_MAX_RECORDS_PER_PERSON = 100
DEFAULT_MAX_OBSERVATION_MONTHS = 120
DEFAULT_COMPARISON_ALERT_THRESHOLD = 5.0

# Domain configuration (from achilles_like settings.py)
DOMAIN_CONFIG = {
    "Condition": {
        "table": "condition_occurrence",
        "person_id": "person_id",
        "date_col": "condition_start_date",
        "concept_id": "condition_concept_id",
        "source_value": "condition_source_value",
        "source_concept_id": "condition_source_concept_id",
    },
    "Drug": {
        "table": "drug_exposure",
        "person_id": "person_id",
        "date_col": "drug_exposure_start_date",
        "concept_id": "drug_concept_id",
        "source_value": "drug_source_value",
        "source_name": "drug_source_name",
        "source_concept_id": "drug_source_concept_id",
        "source_atc": "drug_source_atc",
    },
    "Measurement": {
        "table": "measurement",
        "person_id": "person_id",
        "date_col": "measurement_date",
        "concept_id": "measurement_concept_id",
        "source_value": "measurement_source_value",
        "source_name": "measurement_source_name",
        "source_concept_id": "measurement_source_concept_id",
    },
    "Observation": {
        "table": "observation",
        "person_id": "person_id",
        "date_col": "observation_date",
        "concept_id": "observation_concept_id",
        "source_value": "observation_source_value",
        "source_concept_id": "observation_source_concept_id",
    },
    "Procedure": {
        "table": "procedure_occurrence",
        "person_id": "person_id",
        "date_col": "procedure_date",
        "concept_id": "procedure_concept_id",
        "source_value": "procedure_source_value",
        "source_concept_id": "procedure_source_concept_id",
    },
    "Visit": {
        "table": "visit_occurrence",
        "person_id": "person_id",
        "date_col": "visit_start_date",
        "concept_id": "visit_concept_id",
        "source_value": "visit_source_value",
        "source_concept_id": "visit_source_concept_id",
    },
    "Device": {
        "table": "device_exposure",
        "person_id": "person_id",
        "date_col": "device_exposure_start_date",
        "concept_id": "device_concept_id",
        "source_value": "device_source_value",
        "source_concept_id": "device_source_concept_id",
    },
    "Death": {
        "table": "death",
        "person_id": "person_id",
        "date_col": "death_date",
        "concept_id": "cause_concept_id",
        "source_value": "cause_source_value",
        "source_concept_id": "cause_source_concept_id",
    },
    "Specimen": {
        "table": "specimen",
        "person_id": "person_id",
        "date_col": "specimen_date",
        "concept_id": "specimen_concept_id",
        "source_value": "specimen_source_value",
        "source_concept_id": "specimen_source_concept_id",
    },
    "Note": {
        "table": "note",
        "person_id": "person_id",
        "date_col": "note_date",
        "concept_id": "note_type_concept_id",
        "source_value": None,
        "source_concept_id": None,
    },
    "Payer_Plan_Period": {
        "table": "payer_plan_period",
        "person_id": "person_id",
        "date_col": "payer_plan_period_start_date",
        "concept_id": "payer_concept_id",
        "source_value": "payer_source_value",
        "source_concept_id": "payer_source_concept_id",
    },
}

PERSON_DOMAIN_NAME = "Person"
OBSERVATION_PERIOD_DOMAIN_NAME = "ObservationPeriod"
DASHBOARD_DOMAIN_NAME = "Dashboard"

# ── OMOP CDM table categories (official CDM v5.4 grouping) ──
# Real-world OMOP deployments do not always store every table in the same
# PostgreSQL schema (e.g. the vocabulary tables are frequently kept in a
# separate, shared schema). Each OMOP table therefore belongs to an official
# category, and a CDM may map each category to its own schema via the
# `schema_categories` config. Tables whose category has no explicit override
# fall back to the CDM's default `omop_schema`.
OMOP_TABLE_CATEGORIES: dict[str, list[str]] = {
    # Standardized clinical data
    "clinical": [
        "person", "observation_period", "visit_occurrence", "visit_detail",
        "condition_occurrence", "drug_exposure", "procedure_occurrence",
        "device_exposure", "measurement", "observation", "death", "note",
        "note_nlp", "specimen", "fact_relationship",
    ],
    # Standardized health system data
    "health_system": ["location", "care_site", "provider"],
    # Standardized health economics
    "health_economics": ["payer_plan_period", "cost"],
    # Standardized derived elements
    "derived": [
        "condition_era", "drug_era", "dose_era", "episode", "episode_event",
        "cohort", "cohort_definition",
    ],
    # Standardized metadata
    "metadata": ["cdm_source", "metadata"],
    # Standardized vocabularies
    "vocabulary": [
        "concept", "vocabulary", "domain", "concept_class",
        "concept_relationship", "relationship", "concept_synonym",
        "concept_ancestor", "source_to_concept_map", "drug_strength",
    ],
}

# Ordered list of category keys (used by config UI / validation).
OMOP_SCHEMA_CATEGORIES: list[str] = list(OMOP_TABLE_CATEGORIES.keys())

# Reverse lookup: OMOP table name → category key.
TABLE_CATEGORY: dict[str, str] = {
    table: category
    for category, tables in OMOP_TABLE_CATEGORIES.items()
    for table in tables
}

# OHDSI integration.
# The backend no longer touches Docker. OHDSI tools run in a dedicated runner
# service (see ohdsi-tools/runner) that the backend calls over an internal HTTP
# API. Two modes only:
#   OHDSI_MODE=off  -> feature disabled (endpoints return 503, tab hidden)
#   OHDSI_MODE=on   -> backend talks to the runner at OHDSI_RUNNER_URL
OHDSI_MODE = os.getenv("OHDSI_MODE", "off").strip().lower()
OHDSI_ENABLED = OHDSI_MODE == "on"
OHDSI_RUNNER_URL = os.getenv("OHDSI_RUNNER_URL", "http://opal-ohdsi-runner:9000").rstrip("/")
OHDSI_RUNNER_TOKEN = os.getenv("OHDSI_RUNNER_TOKEN", "")

if ENVIRONMENT == "production" and OHDSI_ENABLED and not OHDSI_RUNNER_TOKEN:
    raise RuntimeError(
        "FATAL: OHDSI_MODE=on requires OHDSI_RUNNER_TOKEN in production. "
        "Generate one with: openssl rand -hex 32"
    )
