"""Test fixtures for the standalone bricks (no database required)."""
import sys
from pathlib import Path

import pytest

STANDALONE_DIR = Path(__file__).resolve().parents[1]
if str(STANDALONE_DIR) not in sys.path:
    sys.path.insert(0, str(STANDALONE_DIR))

import opal_standalone  # noqa: E402,F401 - installs the backend bridge
from opal_standalone.config import AnalysisParams, AppConfig, CdmConnection  # noqa: E402
from opal_standalone.store import Store  # noqa: E402


class FakeRow(dict):
    """A row that behaves like a driver row on every engine.

    psycopg2's RealDictCursor hands back mappings, while the dialect's
    ``DictRowCursor`` rebuilds dicts from ``zip(columns, row)`` — which iterates
    the row. Supporting both means mapping access *and* value iteration.
    """

    def __iter__(self):
        return iter(self.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


@pytest.fixture
def cdm() -> CdmConnection:
    return CdmConnection(
        name="test-cdm", host="localhost", database="omop", user="reader",
        schema="omop_cdm", schema_categories={"vocabulary": "omop_vocab"},
    )


@pytest.fixture
def config(cdm, tmp_path) -> AppConfig:
    return AppConfig(
        cdms=[cdm], analysis=AnalysisParams(), storage_path=tmp_path, lang="fr",
    )


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "test.db")
