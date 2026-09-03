"""Read-only connections to the external OMOP CDM database.

The server keeps a per-CDM ``ThreadedConnectionPool``; a standalone app is a
single user driving one query at a time, so it simply opens a connection per
operation and closes it. The important behaviours of the server are kept: a
statement timeout, and a session forced read-only so a standalone brick can
never write to the CDM.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import DictCursor

from opal_standalone.config import CdmConnection
from utils.cdm_helper import SchemaMap, build_schema_map

logger = logging.getLogger(__name__)


def schema_map(cdm: CdmConnection) -> SchemaMap:
    """Schema resolver for a CDM (per-category overrides included)."""
    return build_schema_map(cdm)


def connect(cdm: CdmConnection):
    """Open a psycopg2 connection to the CDM, read-only and timeout-bounded."""
    conn = psycopg2.connect(
        host=cdm.host,
        port=cdm.port,
        dbname=cdm.database,
        user=cdm.user,
        password=cdm.password,
        connect_timeout=10,
        application_name="opal-standalone",
    )
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = %s", (int(cdm.statement_timeout_ms),))
            if cdm.read_only:
                cur.execute("SET default_transaction_read_only = on")
        conn.autocommit = False
    except Exception:
        conn.close()
        raise
    return conn


@contextmanager
def connection(cdm: CdmConnection):
    """Context manager yielding a CDM connection, always closed afterwards."""
    conn = connect(cdm)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover - best effort
            logger.debug("Failed to close CDM connection", exc_info=True)


def test_connection(cdm: CdmConnection) -> dict:
    """Probe the CDM: server version, schema presence and person count."""
    schema = schema_map(cdm)
    with connection(cdm) as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT version() AS version")
            version = cur.fetchone()["version"]
            cur.execute(
                "SELECT COUNT(*) AS n FROM information_schema.tables "
                "WHERE table_schema = %s",
                (schema.schema_for("person"),),
            )
            tables = int(cur.fetchone()["n"])
            persons = None
            try:
                cur.execute(f"SELECT COUNT(*) AS n FROM {schema.t('person')}")
                persons = int(cur.fetchone()["n"])
            except Exception:
                conn.rollback()
    return {
        "server_version": version.split(",")[0],
        "schema": str(schema),
        "tables_in_schema": tables,
        "persons": persons,
    }


def fetch_all(conn, sql: str, params=None) -> list[dict]:
    """Run a SELECT and return a list of dicts."""
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute(sql, params)
        if cur.description is None:
            return []
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def fetch_one(conn, sql: str, params=None) -> dict | None:
    rows = fetch_all(conn, sql, params)
    return rows[0] if rows else None


def has_unaccent(conn) -> bool:
    """Whether the ``unaccent`` extension is available (search falls back if not)."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_proc WHERE proname = 'unaccent' LIMIT 1")
            return cur.fetchone() is not None
    except Exception:
        conn.rollback()
        return False
