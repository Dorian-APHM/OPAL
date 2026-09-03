import json


def test_snapshots_are_versioned_per_domain(store):
    first = store.save_snapshot("cdm", "Person", {"domain": "Person", "n": 1})
    second = store.save_snapshot("cdm", "Person", {"domain": "Person", "n": 2})
    other = store.save_snapshot("cdm", "Drug", {"domain": "Drug"})

    assert (first["version"], second["version"], other["version"]) == (1, 2, 1)
    assert store.latest_snapshot("cdm", "Person")["results"]["n"] == 2
    assert store.analyzed_domains("cdm") == ["Drug", "Person"]
    assert len(store.list_snapshots("cdm", "Person")) == 2

    store.delete_snapshot(second["id"])
    assert store.latest_snapshot("cdm", "Person")["version"] == 1


def test_cohorts_round_trip_and_upsert_by_name(store):
    cohort_id = store.save_cohort("cdm", "diabetes", {"inclusion": {"criteria": []}}, "desc")
    same_id = store.save_cohort("cdm", "diabetes", {"inclusion": {"criteria": [1]}}, "desc2")
    assert cohort_id == same_id

    cohort = store.get_cohort(cohort_id)
    assert cohort["criteria"]["inclusion"]["criteria"] == [1]
    assert cohort["characterization"] is None

    store.set_cohort_result(cohort_id, "characterization", {"cohort_size": 42})
    assert store.get_cohort(cohort_id)["characterization"]["cohort_size"] == 42

    store.delete_cohort(cohort_id)
    assert store.get_cohort(cohort_id) is None


def test_concept_sets_round_trip(store):
    payload = {"concepts": [{"concept_id": 1}], "source_codes": ["A01"]}
    set_id = store.save_concept_set("cdm", "my-set", payload, "desc")
    assert store.get_concept_set(set_id)["payload"] == payload
    assert store.list_concept_sets("cdm")[0]["name"] == "my-set"
    store.delete_concept_set(set_id)
    assert store.list_concept_sets("cdm") == []


def test_mapping_decisions_are_unique_per_source_value(store):
    store.save_decision("cdm", "Drug", {"source_value": "X", "target_concept_id": 1,
                                        "status": "accepted"})
    store.save_decision("cdm", "Drug", {"source_value": "X", "target_concept_id": 2,
                                        "status": "accepted"})
    store.save_decision("cdm", "Condition", {"source_value": "X", "status": "rejected"})

    decisions = store.list_decisions("cdm")
    assert len(decisions) == 2
    drug = store.list_decisions("cdm", "Drug")
    assert drug[0]["target_concept_id"] == 2


def test_analyses_and_lineage_round_trip(store):
    analysis_id = store.save_analysis("incidence", "cdm", "run-1", {"p": 1}, {"rate": 3.2})
    analysis = store.get_analysis(analysis_id)
    assert analysis["parameters"] == {"p": 1}
    assert analysis["results"]["rate"] == 3.2
    assert store.list_analyses("estimation", "cdm") == []

    store.save_lineage("cdm", "etl.html", {"nodes": {}, "edges": []})
    store.save_lineage("cdm", "etl-v2.html", {"nodes": {"a": {}}, "edges": []})
    lineage = store.get_lineage("cdm")
    assert lineage["filename"] == "etl-v2.html"
    assert json.loads(json.dumps(lineage["graph"]))["nodes"] == {"a": {}}
    store.delete_lineage("cdm")
    assert store.get_lineage("cdm") is None


def test_store_accepts_a_directory_path(tmp_path):
    from opal_standalone.store import Store

    store = Store(tmp_path / "nested" / "dir")
    assert store.path.name == "opal-standalone.db"
    assert store.path.exists()
