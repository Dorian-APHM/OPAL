"""Tests for the quality analysis engine routing."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.quality.engine import get_available_domains
from config import DOMAIN_CONFIG, PERSON_DOMAIN_NAME, OBSERVATION_PERIOD_DOMAIN_NAME, DASHBOARD_DOMAIN_NAME
import pytest


def test_available_domains_includes_all():
    """All configured domains should be in available domains."""
    domains = get_available_domains()
    assert DASHBOARD_DOMAIN_NAME in domains
    assert PERSON_DOMAIN_NAME in domains
    assert OBSERVATION_PERIOD_DOMAIN_NAME in domains
    for domain_name in DOMAIN_CONFIG:
        assert domain_name in domains


def test_available_domains_order():
    """Dashboard, Person, ObservationPeriod should come first."""
    domains = get_available_domains()
    assert domains[0] == DASHBOARD_DOMAIN_NAME
    assert domains[1] == PERSON_DOMAIN_NAME
    assert domains[2] == OBSERVATION_PERIOD_DOMAIN_NAME


def test_domain_config_has_required_fields():
    """Each domain config must have table, person_id, date_col, concept_id, source_value."""
    required = {"table", "person_id", "date_col", "concept_id", "source_value"}
    for domain_name, cfg in DOMAIN_CONFIG.items():
        missing = required - set(cfg.keys())
        assert missing == set(), f"{domain_name} missing: {missing}"


def test_domain_config_includes_new_domains():
    """Device and Death should be in the domain config."""
    assert "Device" in DOMAIN_CONFIG
    assert "Death" in DOMAIN_CONFIG
