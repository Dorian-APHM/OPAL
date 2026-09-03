"""Full quality loop through the UI: run an analysis, store it, read it back.

The CDM is a fake connection that answers by query shape, so the whole brick —
Streamlit widgets, engine, SQLite store — is exercised without a database.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "apps" / "quality.py"


class FakeRow(dict):
    """Row behaving like psycopg2's DictRow: mapping access *and* value iteration."""

    def __iter__(self):
        return iter(self.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class FakeCursor:
    """Cursor answering the queries of the flow by inspecting the SQL."""

    def __init__(self):
        self._rows: list[dict] = []
        self.description = [("col",)]

    def execute(self, query, params=None):
        text = str(query)
        if "information_schema.tables" in text:
            self._rows = [{"exists": 1}]
        elif "gender_concept_id" in text and "GROUP BY" in text:
            self._rows = [
                {"gender_concept_id": 8532, "concept_name": "FEMALE", "n": 2},
                {"gender_concept_id": 8507, "concept_name": "MALE", "n": 1},
            ]
        elif "year_of_birth" in text and "GROUP BY" in text:
            self._rows = [{"year_of_birth": 1980, "n": 2}, {"year_of_birth": 1991, "n": 1}]
        elif "race_concept_id" in text:
            self._rows = [{"race_concept_id": 0, "concept_name": "UNKNOWN", "n": 3}]
        elif "ethnicity_concept_id" in text:
            self._rows = [{"ethnicity_concept_id": 0, "concept_name": "UNKNOWN", "n": 3}]
        elif "patient_count" in text:
            self._rows = [{"patient_count": 3}]
        else:
            self._rows = [{"n": 3}]
        self._rows = [FakeRow(row) for row in self._rows]
        keys = list(self._rows[0].keys()) if self._rows else ["col"]
        self.description = [(name,) for name in keys]

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def fake_cdm(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text(
        '[omop]\nname = "fake"\nhost = "127.0.0.1"\nport = 1\n'
        'database = "omop"\nuser = "reader"\nschema = "omop_cdm"\n'
        f'[storage]\npath = "{(tmp_path / "data").as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OPAL_STANDALONE_CONFIG", str(config))

    import streamlit as st

    st.cache_resource.clear()

    connection = MagicMock()
    connection.cursor.return_value = FakeCursor()
    connection.dsn = "fake"
    monkeypatch.setattr("opal_standalone.omop.connect", lambda cdm: connection)
    return tmp_path


def test_running_the_person_analysis_stores_and_renders_a_snapshot(fake_cdm):
    at = AppTest.from_file(str(APP), default_timeout=120)
    at.run()
    assert not at.exception

    domains = at.multiselect(key="quality_domains")
    domains.select("Person").run()
    assert not at.exception

    run_button = next(b for b in at.button if b.label == "Lancer l'analyse")
    run_button.click().run()
    assert not at.exception, [e.value for e in at.exception]

    assert any("snapshot" in message.value.lower() for message in at.success)

    from opal_standalone.store import Store

    store = Store(fake_cdm / "data")
    snapshot = store.latest_snapshot("fake", "Person")
    assert snapshot is not None
    summary = snapshot["results"]["achilles_like"]["person_summary"]
    assert summary["total_persons"] == 3
    assert summary["gender_distribution"]["gender_name"] == ["FEMALE", "MALE"]

    # The stored snapshot is rendered back in the page (metric + history tab).
    assert any(metric.value == "3" for metric in at.metric)


def test_cohort_count_flow(fake_cdm):
    """The cohort brick builds SQL, runs it and renders the count."""
    app = Path(__file__).resolve().parents[1] / "apps" / "cohort.py"
    at = AppTest.from_file(str(app), default_timeout=120)
    at.session_state["cohort_criteria"] = {
        "inclusion": {
            "operator": "AND",
            "criteria": [{"id": "a", "domain": "Condition", "concepts": [{"concept_id": 201826}]}],
            "sameVisit": False,
        },
        "exclusion": {"operator": "OR", "criteria": []},
        "demographics": {},
    }
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    count_button = next(b for b in at.button if b.label == "Compter les patients")
    count_button.click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["cohort_count"] == 3
    assert any(metric.value == "3" for metric in at.metric)


def test_adding_a_criterion_through_the_form(fake_cdm):
    """The criteria form must append to the definition and rerun cleanly."""
    app = Path(__file__).resolve().parents[1] / "apps" / "cohort.py"
    at = AppTest.from_file(str(app), default_timeout=120)
    at.run()

    at.text_input(key="cids_inclusion").set_value("201826, 4329847").run()
    submit = [b for b in at.button if b.label == "Ajouter le critère"][0]
    submit.click().run()
    assert not at.exception, [e.value for e in at.exception]

    criteria = at.session_state["cohort_criteria"]["inclusion"]["criteria"]
    assert len(criteria) == 1
    assert [c["concept_id"] for c in criteria[0]["concepts"]] == [201826, 4329847]
    assert criteria[0]["include_descendants"] is True
