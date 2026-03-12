"""
Dynamic connection to external OMOP CDM PostgreSQL databases.

Uses simple direct connections (no pool) to avoid connection leak issues.
Each request opens and closes its own connection.
"""
import logging

import psycopg2
from psycopg2.extras import DictCursor

logger = logging.getLogger(__name__)

# Statement timeout for CDM queries (5 minutes). Prevents runaway queries.
STATEMENT_TIMEOUT_MS = 300_000


def get_omop_connection(host: str, port: int, dbname: str, user: str, password: str):
    """
    Open a psycopg2 connection to an OMOP CDM database.
    Caller MUST close it in a finally block.
    """
    conn = psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        connect_timeout=10,
        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
    )
    conn.autocommit = False
    return conn


def test_omop_connection(host: str, port: int, dbname: str, user: str, password: str) -> dict:
    """
    Test connectivity to an OMOP CDM database.
    Returns a dict with success status and message.
    """
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            connect_timeout=10,
        )
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT 1")
        conn.close()
        return {"success": True, "message": "Connection successful"}
    except Exception as e:
        return {"success": False, "message": str(e)}
