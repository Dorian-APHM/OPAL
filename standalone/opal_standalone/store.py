"""Local persistence for the standalone apps — one SQLite file, no server.

The web application stores snapshots, cohorts, mapping decisions and concept
sets in its PostgreSQL application database, keyed by user. Standalone has no
users, so the same objects are kept in a single SQLite file (path configured
under ``[storage]``) with the ownership columns dropped.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cdm_name    TEXT NOT NULL,
    domain      TEXT NOT NULL,
    version     INTEGER NOT NULL,
    results     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_snapshots_cdm_domain ON snapshots (cdm_name, domain, version);

CREATE TABLE IF NOT EXISTS cohorts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    cdm_name          TEXT NOT NULL,
    name              TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    criteria          TEXT NOT NULL,
    characterization  TEXT,
    pathways          TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE (cdm_name, name)
);

CREATE TABLE IF NOT EXISTS concept_sets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cdm_name    TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (cdm_name, name)
);

CREATE TABLE IF NOT EXISTS mapping_decisions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    cdm_name            TEXT NOT NULL,
    domain              TEXT NOT NULL,
    source_value        TEXT NOT NULL,
    source_name         TEXT,
    target_concept_id   INTEGER,
    target_concept_name TEXT,
    status              TEXT NOT NULL,
    strategy            TEXT,
    confidence          REAL,
    comment             TEXT,
    decided_at          TEXT NOT NULL,
    UNIQUE (cdm_name, domain, source_value)
);

CREATE TABLE IF NOT EXISTS analyses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    cdm_name    TEXT NOT NULL,
    name        TEXT NOT NULL,
    parameters  TEXT NOT NULL,
    results     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_analyses_kind ON analyses (kind, cdm_name);

CREATE TABLE IF NOT EXISTS lineage (
    cdm_name   TEXT PRIMARY KEY,
    filename   TEXT NOT NULL,
    graph      TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    """SQLite-backed store. Cheap to construct; opens a connection per call."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.is_dir() or not self.path.suffix:
            self.path = self.path / "opal-standalone.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── quality snapshots ────────────────────────────────────────────────
    def save_snapshot(self, cdm_name: str, domain: str, results: dict) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS v FROM snapshots "
                "WHERE cdm_name = ? AND domain = ?",
                (cdm_name, domain),
            ).fetchone()
            version = int(row["v"]) + 1
            created = _now()
            cursor = conn.execute(
                "INSERT INTO snapshots (cdm_name, domain, version, results, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (cdm_name, domain, version, json.dumps(results, default=str), created),
            )
            return {
                "id": cursor.lastrowid,
                "cdm_name": cdm_name,
                "domain": domain,
                "version": version,
                "created_at": created,
                "results": results,
            }

    def list_snapshots(
        self, cdm_name: str | None = None, domain: str | None = None, limit: int = 200
    ) -> list[dict]:
        sql = "SELECT id, cdm_name, domain, version, created_at FROM snapshots"
        clauses, params = [], []
        if cdm_name:
            clauses.append("cdm_name = ?")
            params.append(cdm_name)
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def get_snapshot(self, snapshot_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
        if not row:
            return None
        snapshot = dict(row)
        snapshot["results"] = json.loads(snapshot["results"])
        return snapshot

    def latest_snapshot(self, cdm_name: str, domain: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM snapshots WHERE cdm_name = ? AND domain = ? "
                "ORDER BY version DESC LIMIT 1",
                (cdm_name, domain),
            ).fetchone()
        return self.get_snapshot(int(row["id"])) if row else None

    def analyzed_domains(self, cdm_name: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT domain FROM snapshots WHERE cdm_name = ? ORDER BY domain",
                (cdm_name,),
            ).fetchall()
        return [r["domain"] for r in rows]

    def delete_snapshot(self, snapshot_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))

    # ── cohorts ──────────────────────────────────────────────────────────
    def save_cohort(
        self, cdm_name: str, name: str, criteria: dict, description: str = "",
        cohort_id: int | None = None,
    ) -> int:
        payload = json.dumps(criteria, default=str)
        with self._connect() as conn:
            if cohort_id:
                conn.execute(
                    "UPDATE cohorts SET name = ?, description = ?, criteria = ?, "
                    "updated_at = ? WHERE id = ?",
                    (name, description, payload, _now(), cohort_id),
                )
                return cohort_id
            cursor = conn.execute(
                "INSERT INTO cohorts (cdm_name, name, description, criteria, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (cdm_name, name) DO UPDATE SET "
                "description = excluded.description, criteria = excluded.criteria, "
                "updated_at = excluded.updated_at",
                (cdm_name, name, description, payload, _now(), _now()),
            )
            if cursor.lastrowid:
                return cursor.lastrowid
            row = conn.execute(
                "SELECT id FROM cohorts WHERE cdm_name = ? AND name = ?", (cdm_name, name)
            ).fetchone()
            return int(row["id"])

    def list_cohorts(self, cdm_name: str | None = None) -> list[dict]:
        sql = "SELECT id, cdm_name, name, description, created_at, updated_at FROM cohorts"
        params: list = []
        if cdm_name:
            sql += " WHERE cdm_name = ?"
            params.append(cdm_name)
        sql += " ORDER BY updated_at DESC"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def get_cohort(self, cohort_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM cohorts WHERE id = ?", (cohort_id,)).fetchone()
        if not row:
            return None
        cohort = dict(row)
        cohort["criteria"] = json.loads(cohort["criteria"])
        for key in ("characterization", "pathways"):
            cohort[key] = json.loads(cohort[key]) if cohort[key] else None
        return cohort

    def set_cohort_result(self, cohort_id: int, key: str, value: dict) -> None:
        if key not in ("characterization", "pathways"):
            raise ValueError(f"Unknown cohort result '{key}'")
        with self._connect() as conn:
            conn.execute(
                f"UPDATE cohorts SET {key} = ?, updated_at = ? WHERE id = ?",
                (json.dumps(value, default=str), _now(), cohort_id),
            )

    def delete_cohort(self, cohort_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM cohorts WHERE id = ?", (cohort_id,))

    # ── concept sets ─────────────────────────────────────────────────────
    def save_concept_set(
        self, cdm_name: str, name: str, payload: dict, description: str = "",
        concept_set_id: int | None = None,
    ) -> int:
        blob = json.dumps(payload, default=str)
        with self._connect() as conn:
            if concept_set_id:
                conn.execute(
                    "UPDATE concept_sets SET name = ?, description = ?, payload = ?, "
                    "updated_at = ? WHERE id = ?",
                    (name, description, blob, _now(), concept_set_id),
                )
                return concept_set_id
            cursor = conn.execute(
                "INSERT INTO concept_sets (cdm_name, name, description, payload, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (cdm_name, name) DO UPDATE SET "
                "description = excluded.description, payload = excluded.payload, "
                "updated_at = excluded.updated_at",
                (cdm_name, name, description, blob, _now(), _now()),
            )
            if cursor.lastrowid:
                return cursor.lastrowid
            row = conn.execute(
                "SELECT id FROM concept_sets WHERE cdm_name = ? AND name = ?",
                (cdm_name, name),
            ).fetchone()
            return int(row["id"])

    def list_concept_sets(self, cdm_name: str | None = None) -> list[dict]:
        sql = "SELECT id, cdm_name, name, description, payload, updated_at FROM concept_sets"
        params: list = []
        if cdm_name:
            sql += " WHERE cdm_name = ?"
            params.append(cdm_name)
        sql += " ORDER BY updated_at DESC"
        with self._connect() as conn:
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        for row in rows:
            row["payload"] = json.loads(row["payload"])
        return rows

    def get_concept_set(self, concept_set_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM concept_sets WHERE id = ?", (concept_set_id,)
            ).fetchone()
        if not row:
            return None
        concept_set = dict(row)
        concept_set["payload"] = json.loads(concept_set["payload"])
        return concept_set

    def delete_concept_set(self, concept_set_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM concept_sets WHERE id = ?", (concept_set_id,))

    # ── mapping decisions ────────────────────────────────────────────────
    def save_decision(self, cdm_name: str, domain: str, decision: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO mapping_decisions (cdm_name, domain, source_value, source_name, "
                "target_concept_id, target_concept_name, status, strategy, confidence, comment, decided_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (cdm_name, domain, source_value) DO UPDATE SET "
                "source_name = excluded.source_name, "
                "target_concept_id = excluded.target_concept_id, "
                "target_concept_name = excluded.target_concept_name, "
                "status = excluded.status, strategy = excluded.strategy, "
                "confidence = excluded.confidence, comment = excluded.comment, "
                "decided_at = excluded.decided_at",
                (
                    cdm_name, domain,
                    decision.get("source_value"), decision.get("source_name"),
                    decision.get("target_concept_id"), decision.get("target_concept_name"),
                    decision.get("status", "accepted"), decision.get("strategy"),
                    decision.get("confidence"), decision.get("comment"), _now(),
                ),
            )

    def list_decisions(self, cdm_name: str, domain: str | None = None) -> list[dict]:
        sql = "SELECT * FROM mapping_decisions WHERE cdm_name = ?"
        params: list = [cdm_name]
        if domain:
            sql += " AND domain = ?"
            params.append(domain)
        sql += " ORDER BY decided_at DESC"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def delete_decision(self, decision_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM mapping_decisions WHERE id = ?", (decision_id,))

    # ── incidence / estimation analyses ──────────────────────────────────
    def save_analysis(
        self, kind: str, cdm_name: str, name: str, parameters: dict, results: dict
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO analyses (kind, cdm_name, name, parameters, results, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    kind, cdm_name, name,
                    json.dumps(parameters, default=str),
                    json.dumps(results, default=str),
                    _now(),
                ),
            )
            return int(cursor.lastrowid)

    def list_analyses(self, kind: str, cdm_name: str | None = None) -> list[dict]:
        sql = "SELECT id, kind, cdm_name, name, created_at FROM analyses WHERE kind = ?"
        params: list = [kind]
        if cdm_name:
            sql += " AND cdm_name = ?"
            params.append(cdm_name)
        sql += " ORDER BY created_at DESC"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def get_analysis(self, analysis_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM analyses WHERE id = ?", (analysis_id,)
            ).fetchone()
        if not row:
            return None
        analysis = dict(row)
        analysis["parameters"] = json.loads(analysis["parameters"])
        analysis["results"] = json.loads(analysis["results"])
        return analysis

    def delete_analysis(self, analysis_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))

    # ── lineage ──────────────────────────────────────────────────────────
    def save_lineage(self, cdm_name: str, filename: str, graph: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO lineage (cdm_name, filename, graph, created_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT (cdm_name) DO UPDATE SET filename = excluded.filename, "
                "graph = excluded.graph, created_at = excluded.created_at",
                (cdm_name, filename, json.dumps(graph, default=str), _now()),
            )

    def get_lineage(self, cdm_name: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM lineage WHERE cdm_name = ?", (cdm_name,)
            ).fetchone()
        if not row:
            return None
        lineage = dict(row)
        lineage["graph"] = json.loads(lineage["graph"])
        return lineage

    def delete_lineage(self, cdm_name: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM lineage WHERE cdm_name = ?", (cdm_name,))
