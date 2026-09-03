"""The install self-check (`python standalone/run.py --check`)."""
import subprocess
import sys
from pathlib import Path

from opal_standalone import diagnostics
from opal_standalone.config import parse_config

STANDALONE_DIR = Path(__file__).resolve().parents[1]

CONFIG = """
[omop]
name = "demo"
host = "127.0.0.1"
port = 1
database = "omop"
user = "reader"
schema = "omop_cdm"

[storage]
path = "{storage}"
"""


def _config(tmp_path, **overrides):
    raw = {
        "omop": {"name": "demo", "host": "h", "database": "d", "user": "u",
                 "schema": "omop_cdm", **overrides},
        "storage": {"path": str(tmp_path)},
    }
    return parse_config(raw, source=tmp_path / "config.toml")


def test_reports_a_healthy_cdm(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "opal_standalone.omop.test_connection",
        lambda cdm: {"engine": "PostgreSQL", "schema": "omop_cdm",
                     "tables_in_schema": 42, "persons": 1234},
    )
    config = _config(tmp_path)
    checks = diagnostics.run_diagnostics(config)
    assert [c.ok for c in checks] == [True]

    report = diagnostics.format_report(config, checks)
    assert "Pilote        : OK" in report
    assert "42 tables" in report
    assert "1 234 patients" in report
    assert "tout est prêt" in report


def test_reports_an_unreachable_cdm(tmp_path, monkeypatch):
    def _boom(cdm):
        raise OSError("connection refused")

    monkeypatch.setattr("opal_standalone.omop.test_connection", _boom)
    config = _config(tmp_path)
    checks = diagnostics.run_diagnostics(config)
    assert not checks[0].ok
    report = diagnostics.format_report(config, checks)
    assert "ÉCHEC — connection refused" in report
    assert "au moins une base est inaccessible" in report


def test_reports_a_missing_driver(tmp_path, monkeypatch):
    monkeypatch.setattr("opal_standalone.omop.driver_status",
                        lambda cdm: (False, "pip install oracledb"))
    config = _config(tmp_path, db_type="oracle")
    check = diagnostics.run_diagnostics(config)[0]
    assert not check.ok and not check.driver_ok
    assert "oracledb" in diagnostics.format_report(config, [check])


def test_cli_check_exits_non_zero_when_the_cdm_is_unreachable(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG.format(storage=(tmp_path / "data").as_posix()), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(STANDALONE_DIR / "run.py"), "--check", "--config", str(path)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 1
    assert "Base « demo »" in result.stdout
    assert "Stockage local" in result.stdout


def test_cli_check_reports_an_invalid_configuration(tmp_path):
    result = subprocess.run(
        [sys.executable, str(STANDALONE_DIR / "run.py"), "--check",
         "--config", str(tmp_path / "absent.toml")],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 1
    assert "Configuration invalide" in result.stderr
