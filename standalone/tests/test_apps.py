"""Each brick must start on its own — rendered end to end by Streamlit's AppTest.

The configuration points at an unreachable database, so the apps are exercised
exactly as they behave before a CDM answers: every connection failure must be
handled by the view, never surface as an uncaught exception.
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APPS_DIR = Path(__file__).resolve().parents[1] / "apps"
APPS = sorted(p.stem for p in APPS_DIR.glob("*.py"))

CONFIG = """
[omop]
name = "unreachable"
db_type = "{db_type}"
host = "127.0.0.1"
port = 1
database = "omop"
user = "reader"
schema = "omop_cdm"

[storage]
path = "{storage}"
"""


def _write_config(tmp_path, monkeypatch, db_type="postgresql"):
    path = tmp_path / "config.toml"
    path.write_text(
        CONFIG.format(db_type=db_type, storage=(tmp_path / "data").as_posix()),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPAL_STANDALONE_CONFIG", str(path))
    return path


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    return _write_config(tmp_path, monkeypatch)


def test_every_brick_has_an_entrypoint():
    assert set(APPS) >= {
        "opal", "quality", "cohort", "concepts", "concept_sets", "mapping",
        "incidence", "estimation", "datamanagement", "lineage",
    }


@pytest.mark.parametrize("app", APPS)
def test_app_runs_without_uncaught_exception(app, config_file):
    at = AppTest.from_file(str(APPS_DIR / f"{app}.py"), default_timeout=60)
    at.run()
    assert not at.exception, f"{app}: {[e.value for e in at.exception]}"
    assert at.title, f"{app}: no page title rendered"


@pytest.mark.parametrize("app", ["quality", "cohort", "concepts", "mapping", "datamanagement"])
@pytest.mark.parametrize("db_type", ["oracle", "sqlserver"])
def test_apps_run_against_a_non_postgres_cdm(app, db_type, tmp_path, monkeypatch):
    """A CDM declared as Oracle / SQL Server must not break the pages.

    The database is unreachable (and the driver may not even be installed), so
    this pins that every engine-specific failure is handled by the view.
    """
    import streamlit as st

    st.cache_resource.clear()
    _write_config(tmp_path, monkeypatch, db_type=db_type)
    at = AppTest.from_file(str(APPS_DIR / f"{app}.py"), default_timeout=60)
    at.run()
    assert not at.exception, f"{app}/{db_type}: {[e.value for e in at.exception]}"
    assert at.title


def test_missing_configuration_is_reported_not_raised(tmp_path, monkeypatch):
    import streamlit as st

    st.cache_resource.clear()  # the config is cached process-wide across runs
    monkeypatch.setenv("OPAL_STANDALONE_CONFIG", str(tmp_path / "absent.toml"))
    at = AppTest.from_file(str(APPS_DIR / "quality.py"), default_timeout=60)
    at.run()
    assert not at.exception
    assert any("Configuration" in error.value for error in at.error)
