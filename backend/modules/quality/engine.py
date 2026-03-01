"""
Quality analysis engine — orchestrates domain analyses.
Replaces achilles_like's run_domain_analysis() function.
"""
import logging

from config import (
    DOMAIN_CONFIG,
    PERSON_DOMAIN_NAME,
    OBSERVATION_PERIOD_DOMAIN_NAME,
    DASHBOARD_DOMAIN_NAME,
    DEFAULT_TOP_UNMAPPED_TERMS,
    DEFAULT_TOP_CONCEPTS,
    DEFAULT_MAX_RECORDS_PER_PERSON,
)
from modules.quality.domains.person import run_person_analysis
from modules.quality.domains.observation_period import run_observation_period_analysis
from modules.quality.domains.dashboard import run_dashboard_analysis
from modules.quality.domains.clinical import run_clinical_domain_analysis

logger = logging.getLogger(__name__)


def get_available_domains(conn=None, omop_schema: str = "omop_cdm") -> list[str]:
    """Return list of available analysis domains.

    If a CDM connection is provided, only include clinical domains whose
    tables actually exist in the CDM schema. This avoids showing domains
    like Specimen, Note, or Payer_Plan_Period when the CDM doesn't have them.
    """
    domains = [DASHBOARD_DOMAIN_NAME, PERSON_DOMAIN_NAME, OBSERVATION_PERIOD_DOMAIN_NAME]
    if conn:
        try:
            cur = conn.cursor()
            for domain_name, cfg in DOMAIN_CONFIG.items():
                table = cfg["table"]
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = %s LIMIT 1",
                    (omop_schema, table),
                )
                if cur.fetchone():
                    domains.append(domain_name)
            cur.close()
        except Exception:
            # Fallback: return all domains
            domains.extend(list(DOMAIN_CONFIG.keys()))
    else:
        domains.extend(list(DOMAIN_CONFIG.keys()))
    return domains


def run_domain_analysis(
    conn,
    domain_name: str,
    omop_schema: str = "omop_cdm",
    top_unmapped: int = DEFAULT_TOP_UNMAPPED_TERMS,
    top_concepts: int = DEFAULT_TOP_CONCEPTS,
    max_records_per_person: int = DEFAULT_MAX_RECORDS_PER_PERSON,
    max_observation_months: int | None = None,
) -> dict:
    """
    Execute analysis for a given domain. Routes to the appropriate
    domain-specific analysis function.
    """
    logger.info("Running analysis for domain: %s (schema: %s)", domain_name, omop_schema)

    if domain_name == DASHBOARD_DOMAIN_NAME:
        return run_dashboard_analysis(conn, omop_schema=omop_schema)

    if domain_name == PERSON_DOMAIN_NAME:
        return run_person_analysis(conn, omop_schema=omop_schema)

    if domain_name == OBSERVATION_PERIOD_DOMAIN_NAME:
        return run_observation_period_analysis(
            conn, omop_schema=omop_schema, cap_months=max_observation_months
        )

    if domain_name in DOMAIN_CONFIG:
        return run_clinical_domain_analysis(
            conn,
            domain_name,
            omop_schema=omop_schema,
            top_unmapped=top_unmapped,
            top_concepts=top_concepts,
            max_records_per_person=max_records_per_person,
        )

    raise ValueError(f"Unknown domain: {domain_name}")
