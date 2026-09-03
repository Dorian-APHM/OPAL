import pytest

from opal_standalone.config import ConfigError, load_config, parse_config


def _raw(**overrides):
    raw = {
        "omop": {
            "name": "demo", "host": "db.example", "port": 5433, "database": "omop",
            "user": "reader", "password": "secret", "schema": "omop_cdm",
            "schema_categories": {"vocabulary": "omop_vocab"},
        }
    }
    raw.update(overrides)
    return raw


def test_parses_a_single_connection():
    config = parse_config(_raw())
    cdm = config.cdm()
    assert config.names == ["demo"]
    assert (cdm.host, cdm.port, cdm.schema_categories) == (
        "db.example", 5433, {"vocabulary": "omop_vocab"}
    )
    assert config.analysis.top_concepts == 50


def test_extra_connections_are_listed():
    config = parse_config(_raw(cdm=[{"name": "second", "host": "h", "database": "d", "user": "u"}]))
    assert config.names == ["demo", "second"]
    assert config.cdm("second").schema == "omop_cdm"


def test_missing_keys_are_rejected():
    with pytest.raises(ConfigError):
        parse_config({"omop": {"host": "h"}})


def test_no_connection_is_rejected():
    with pytest.raises(ConfigError):
        parse_config({"analysis": {}})


def test_duplicate_names_are_rejected():
    with pytest.raises(ConfigError):
        parse_config(_raw(cdm=[{"name": "demo", "host": "h", "database": "d", "user": "u"}]))


def test_environment_overrides_the_first_connection(monkeypatch):
    monkeypatch.setenv("OPAL_OMOP_PASSWORD", "from-env")
    monkeypatch.setenv("OPAL_OMOP_HOST", "other.example")
    config = parse_config(_raw())
    assert config.cdm().password == "from-env"
    assert config.cdm().host == "other.example"


def test_storage_path_is_relative_to_the_config_file(tmp_path):
    source = tmp_path / "config.toml"
    config = parse_config(_raw(storage={"path": "./local"}), source=source)
    assert config.storage_path == (tmp_path / "local")


def test_load_config_reports_a_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.toml")


def test_load_config_reads_a_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[omop]\nhost = "h"\ndatabase = "d"\nuser = "u"\n'
        '[analysis]\ntop_concepts = 7\n',
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.cdm().name == "omop"
    assert config.analysis.top_concepts == 7
