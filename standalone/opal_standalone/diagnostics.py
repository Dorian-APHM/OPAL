"""Self-check for a standalone install: configuration, driver, CDM, storage.

Used by ``python standalone/run.py --check``. Deliberately free of Streamlit
imports so it can be run headless (support, CI, a first install over SSH).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from opal_standalone.config import AppConfig, CdmConnection


@dataclass
class CdmCheck:
    """Outcome of the checks run against one configured CDM."""

    name: str
    engine: str
    target: str
    schema: str
    driver_ok: bool
    driver_hint: str = ""
    connected: bool = False
    details: dict = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.driver_ok and self.connected


def check_cdm(cdm: CdmConnection) -> CdmCheck:
    """Probe one CDM: driver present, connection open, schema readable."""
    from opal_standalone.omop import driver_status, test_connection

    driver_ok, driver_hint = driver_status(cdm)
    check = CdmCheck(
        name=cdm.name,
        engine=cdm.db_type,
        target=f"{cdm.user}@{cdm.host}:{cdm.port}/{cdm.database}",
        schema=cdm.schema,
        driver_ok=driver_ok,
        driver_hint=driver_hint,
    )
    if not driver_ok:
        check.error = f"pilote absent — {driver_hint}"
        return check
    try:
        check.details = test_connection(cdm)
        check.connected = True
    except Exception as exc:  # noqa: BLE001 - the message is the diagnostic
        check.error = str(exc).strip().splitlines()[0] if str(exc).strip() else repr(exc)
    return check


def run_diagnostics(config: AppConfig) -> list[CdmCheck]:
    """Check every CDM declared in the configuration file."""
    return [check_cdm(cdm) for cdm in config.cdms]


def storage_line(config: AppConfig) -> str:
    from opal_standalone.store import Store

    store = Store(config.storage_path)
    size = store.path.stat().st_size if store.path.exists() else 0
    return f"{store.path} ({size / 1024:.0f} ko)"


def format_report(config: AppConfig, checks: list[CdmCheck]) -> str:
    """Human-readable report — one block per CDM, plus the local storage."""
    lines = [f"Configuration   : {config.source_path or '(par défaut)'}"]
    for check in checks:
        lines.append("")
        lines.append(f"Base « {check.name} » : {check.engine} — {check.target}")
        lines.append(f"  Schéma        : {check.schema}")
        lines.append(
            f"  Pilote        : {'OK' if check.driver_ok else 'ABSENT — ' + check.driver_hint}"
        )
        if check.connected:
            details = check.details
            persons = details.get("persons")
            summary = (
                f"OK — {details.get('engine')}, "
                f"{details.get('tables_in_schema', 0)} tables dans « {details.get('schema')} »"
            )
            if persons is not None:
                summary += f", {persons:,} patients".replace(",", " ")
            lines.append(f"  Connexion     : {summary}")
        elif check.driver_ok:
            lines.append(f"  Connexion     : ÉCHEC — {check.error}")
    lines.append("")
    lines.append(f"Stockage local  : {storage_line(config)}")
    lines.append(
        "Résultat        : "
        + ("tout est prêt." if all(c.ok for c in checks) else "au moins une base est inaccessible.")
    )
    return "\n".join(lines)
