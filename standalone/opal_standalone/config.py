"""Configuration for the standalone apps: one TOML file, nothing else.

Lookup order for the file:

1. the path given to :func:`load_config`;
2. ``$OPAL_STANDALONE_CONFIG``;
3. ``standalone/config.toml``.

Every value can be overridden by an environment variable (handy for passwords in
a shell profile or a CI run) — see :data:`_ENV_OVERRIDES`.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from opal_standalone.bootstrap import STANDALONE_DIR

DEFAULT_CONFIG_PATH = STANDALONE_DIR / "config.toml"
EXAMPLE_CONFIG_PATH = STANDALONE_DIR / "config.example.toml"

# env var -> (section, key) applied to the *first* CDM connection
_ENV_OVERRIDES = {
    "OPAL_OMOP_HOST": "host",
    "OPAL_OMOP_PORT": "port",
    "OPAL_OMOP_DATABASE": "database",
    "OPAL_OMOP_USER": "user",
    "OPAL_OMOP_PASSWORD": "password",
    "OPAL_OMOP_SCHEMA": "schema",
}


class ConfigError(RuntimeError):
    """Raised when the configuration file is missing or invalid."""


@dataclass
class CdmConnection:
    """Connection details for one OMOP CDM database (read-only)."""

    name: str
    host: str
    port: int = 5432
    database: str = "omop"
    user: str = "postgres"
    password: str = ""
    schema: str = "omop_cdm"
    schema_categories: dict[str, str] = field(default_factory=dict)
    statement_timeout_ms: int = 1_800_000
    read_only: bool = True

    def label(self) -> str:
        return f"{self.name} ({self.user}@{self.host}:{self.port}/{self.database})"


@dataclass
class AnalysisParams:
    """Tunables shared by the quality analyses (same defaults as the server)."""

    top_unmapped_terms: int = 50
    top_concepts: int = 50
    max_records_per_person: int = 100
    max_observation_months: int = 120
    comparison_alert_threshold: float = 5.0


@dataclass
class AppConfig:
    cdms: list[CdmConnection]
    analysis: AnalysisParams
    storage_path: Path
    lang: str = "fr"
    source_path: Path | None = None

    def cdm(self, name: str | None = None) -> CdmConnection:
        """Return the named CDM, or the first one when ``name`` is omitted."""
        if name is None:
            return self.cdms[0]
        for cdm in self.cdms:
            if cdm.name == name:
                return cdm
        raise ConfigError(f"Unknown CDM '{name}' in {self.source_path}")

    @property
    def names(self) -> list[str]:
        return [cdm.name for cdm in self.cdms]


def _connection_from(raw: dict, *, fallback_name: str) -> CdmConnection:
    if not isinstance(raw, dict):
        raise ConfigError("A CDM connection must be a TOML table")
    missing = [k for k in ("host", "database", "user") if not raw.get(k)]
    if missing:
        raise ConfigError(
            f"CDM '{raw.get('name', fallback_name)}': missing required key(s) "
            + ", ".join(missing)
        )
    return CdmConnection(
        name=str(raw.get("name") or fallback_name),
        host=str(raw["host"]),
        port=int(raw.get("port", 5432)),
        database=str(raw["database"]),
        user=str(raw["user"]),
        password=str(raw.get("password", "")),
        schema=str(raw.get("schema", "omop_cdm")),
        schema_categories={
            str(k): str(v) for k, v in (raw.get("schema_categories") or {}).items()
        },
        statement_timeout_ms=int(raw.get("statement_timeout_ms", 1_800_000)),
        read_only=bool(raw.get("read_only", True)),
    )


def _apply_env_overrides(cdm: CdmConnection) -> None:
    for env_name, attr in _ENV_OVERRIDES.items():
        value = os.environ.get(env_name)
        if value is None or value == "":
            continue
        setattr(cdm, attr, int(value) if attr == "port" else value)


def config_path(explicit: str | os.PathLike | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("OPAL_STANDALONE_CONFIG")
    if env:
        return Path(env).expanduser()
    return DEFAULT_CONFIG_PATH


def parse_config(raw: dict, source: Path | None = None) -> AppConfig:
    """Build an :class:`AppConfig` from an already-parsed TOML mapping."""
    connections: list[CdmConnection] = []
    if raw.get("omop"):
        connections.append(_connection_from(raw["omop"], fallback_name="omop"))
    for index, entry in enumerate(raw.get("cdm") or []):
        connections.append(_connection_from(entry, fallback_name=f"cdm-{index + 1}"))
    if not connections:
        raise ConfigError(
            "No OMOP connection configured: add an [omop] section (see "
            f"{EXAMPLE_CONFIG_PATH.name})"
        )

    seen: set[str] = set()
    for cdm in connections:
        if cdm.name in seen:
            raise ConfigError(f"Duplicate CDM name '{cdm.name}'")
        seen.add(cdm.name)
    _apply_env_overrides(connections[0])

    analysis_raw = raw.get("analysis") or {}
    analysis = AnalysisParams(
        top_unmapped_terms=int(analysis_raw.get("top_unmapped_terms", 50)),
        top_concepts=int(analysis_raw.get("top_concepts", 50)),
        max_records_per_person=int(analysis_raw.get("max_records_per_person", 100)),
        max_observation_months=int(analysis_raw.get("max_observation_months", 120)),
        comparison_alert_threshold=float(
            analysis_raw.get("comparison_alert_threshold", 5.0)
        ),
    )

    storage_raw = (raw.get("storage") or {}).get("path")
    if storage_raw:
        storage = Path(str(storage_raw)).expanduser()
        if not storage.is_absolute() and source is not None:
            storage = (source.parent / storage).resolve()
    else:
        storage = STANDALONE_DIR / "data"

    ui_raw = raw.get("ui") or {}
    return AppConfig(
        cdms=connections,
        analysis=analysis,
        storage_path=storage,
        lang=str(ui_raw.get("lang", "fr")),
        source_path=source,
    )


def load_config(path: str | os.PathLike | None = None) -> AppConfig:
    """Read and validate the standalone configuration file."""
    resolved = config_path(path)
    if not resolved.exists():
        raise ConfigError(
            f"Configuration file not found: {resolved}\n"
            f"Copy {EXAMPLE_CONFIG_PATH} to {DEFAULT_CONFIG_PATH} and fill in "
            "your OMOP connection."
        )
    try:
        with open(resolved, "rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {resolved}: {exc}") from exc
    return parse_config(raw, source=resolved.resolve())
