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

# Application database
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://opal:opal@opal-db:5432/opal")

# Security
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY or SECRET_KEY == "change-me-in-production":
    _logger.warning(
        "SECRET_KEY is not set or uses the insecure default. "
        "Set a strong SECRET_KEY environment variable for production. "
        "Generate one with: openssl rand -hex 32"
    )
    if not SECRET_KEY:
        SECRET_KEY = "change-me-in-production"
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://keycloak:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "opal")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "opal-frontend")

# CORS
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")

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
    },
    "Drug": {
        "table": "drug_exposure",
        "person_id": "person_id",
        "date_col": "drug_exposure_start_date",
        "concept_id": "drug_concept_id",
        "source_value": "drug_source_value",
        "source_name": "drug_source_name",
    },
    "Measurement": {
        "table": "measurement",
        "person_id": "person_id",
        "date_col": "measurement_date",
        "concept_id": "measurement_concept_id",
        "source_value": "measurement_source_value",
        "source_name": "measurement_source_name",
    },
    "Observation": {
        "table": "observation",
        "person_id": "person_id",
        "date_col": "observation_date",
        "concept_id": "observation_concept_id",
        "source_value": "observation_source_value",
    },
    "Procedure": {
        "table": "procedure_occurrence",
        "person_id": "person_id",
        "date_col": "procedure_date",
        "concept_id": "procedure_concept_id",
        "source_value": "procedure_source_value",
    },
    "Visit": {
        "table": "visit_occurrence",
        "person_id": "person_id",
        "date_col": "visit_start_date",
        "concept_id": "visit_concept_id",
        "source_value": "visit_source_value",
    },
    "Device": {
        "table": "device_exposure",
        "person_id": "person_id",
        "date_col": "device_exposure_start_date",
        "concept_id": "device_concept_id",
        "source_value": "device_source_value",
    },
    "Death": {
        "table": "death",
        "person_id": "person_id",
        "date_col": "death_date",
        "concept_id": "cause_concept_id",
        "source_value": "cause_source_value",
    },
}

PERSON_DOMAIN_NAME = "Person"
OBSERVATION_PERIOD_DOMAIN_NAME = "ObservationPeriod"
DASHBOARD_DOMAIN_NAME = "Dashboard"

# OHDSI Docker integration
OHDSI_IMAGE_PREFIX = os.getenv("OHDSI_IMAGE_PREFIX", "ohdsi-docker")
OHDSI_OUTPUT_DIR = os.getenv("OHDSI_OUTPUT_DIR", "/app/ohdsi_output")
OHDSI_HOST_OUTPUT_DIR = os.getenv("OHDSI_HOST_OUTPUT_DIR", "")
OHDSI_HOST_SCRIPTS_DIR = os.getenv("OHDSI_HOST_SCRIPTS_DIR", "")
OHDSI_HOST_JDBC_DIR = os.getenv("OHDSI_HOST_JDBC_DIR", "/data/jdbc_drivers")
