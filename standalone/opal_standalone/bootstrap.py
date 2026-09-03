"""Bootstrap for the standalone (Streamlit) apps.

The standalone bricks reuse OPAL's *analysis engines* verbatim — the code in
``backend/modules/**`` that talks to the OMOP CDM through the engine dialects
(``db.dialects``: PostgreSQL, Oracle, SQL Server). Those engines are pure: they
only need ``psycopg2`` (plus the optional driver of the engine actually used),
``config``, ``db.dialects`` and ``utils.sql_safety``. Three backend modules they
touch are, however, tied to the server deployment (FastAPI, SQLAlchemy, the
application database, Keycloak):

* ``utils.cdm_helper``      — CDM lookup in the app DB + FastAPI ``HTTPException``
* ``utils.reference_labels``— reference codebooks stored in the app DB
* ``db.app_db``             — the SQLAlchemy session factory

This module puts ``backend/`` on ``sys.path`` and substitutes standalone
replacements for exactly those three modules, so importing an engine pulls in
psycopg2 and the dialect layer, and nothing else. Everything else (domain analyses, conformity, the
cohort SQL builder, mapping suggestions, incidence, survival, extraction,
lineage) is the *same code the server runs* — no fork, no copy to keep in sync.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

STANDALONE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = STANDALONE_DIR.parent

_installed = False


def backend_dir() -> Path:
    """Directory holding OPAL's backend package (overridable for tests)."""
    env = os.environ.get("OPAL_BACKEND_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return REPO_ROOT / "backend"


def _default_env() -> None:
    """Neutralise the server-oriented settings read by ``backend/config.py``.

    The standalone apps have no application database, no authentication and no
    companion services; these defaults keep ``config`` importable and silent.
    """
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("AUTH_ENABLED", "false")
    os.environ.setdefault("SECRET_KEY", "standalone-no-secret-needed")
    os.environ.setdefault("DATABASE_URL", "sqlite:///standalone-unused.db")
    os.environ.setdefault("OHDSI_MODE", "off")
    os.environ.setdefault("COHORT_LLM_MODE", "off")
    os.environ.setdefault("SAPBERT_MODE", "off")


def _install_shim(target: str, module) -> None:
    """Register ``module`` under the backend module name ``target``."""
    package_name, _, attribute = target.rpartition(".")
    package = importlib.import_module(package_name)
    sys.modules[target] = module
    setattr(package, attribute, module)


def install() -> Path:
    """Make ``backend`` importable and install the standalone shims (idempotent)."""
    global _installed
    if _installed:
        return backend_dir()

    path = backend_dir()
    if not (path / "config.py").exists():
        raise RuntimeError(
            f"OPAL backend not found at {path}. The standalone apps reuse the "
            "analysis engines from the repository; run them from a checkout, or "
            "set OPAL_BACKEND_DIR to the backend directory."
        )

    _default_env()
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

    from opal_standalone.shims import app_db as _app_db
    from opal_standalone.shims import cdm_helper as _cdm_helper
    from opal_standalone.shims import reference_labels as _reference_labels

    _install_shim("utils.cdm_helper", _cdm_helper)
    _install_shim("utils.reference_labels", _reference_labels)
    _install_shim("db.app_db", _app_db)

    _installed = True
    return path
