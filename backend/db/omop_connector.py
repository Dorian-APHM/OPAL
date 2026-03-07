"""
Dynamic connection to external OMOP CDM PostgreSQL databases.

Uses a per-DSN connection pool (psycopg2 ThreadedConnectionPool) so that
connections are reused across requests instead of opened/closed each time.
"""
import logging
import threading

import psycopg2
from psycopg2.extras import DictCursor
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)

# Statement timeout for CDM queries (5 minutes). Prevents runaway queries.
STATEMENT_TIMEOUT_MS = 300_000

# Pool cache: keyed by (host, port, dbname, user)
_pools: dict[tuple, ThreadedConnectionPool] = {}
_pools_lock = threading.Lock()

# Pool sizing
_POOL_MIN = 1
_POOL_MAX = 10


def _get_pool(host: str, port: int, dbname: str, user: str, password: str) -> ThreadedConnectionPool:
    """Get or create a connection pool for the given CDM."""
    key = (host, port, dbname, user)
    pool = _pools.get(key)
    if pool and not pool.closed:
        return pool
    with _pools_lock:
        pool = _pools.get(key)
        if pool and not pool.closed:
            return pool
        logger.info("Creating connection pool for %s@%s:%s/%s", user, host, port, dbname)
        pool = ThreadedConnectionPool(
            _POOL_MIN,
            _POOL_MAX,
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            connect_timeout=10,
            options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
        )
        _pools[key] = pool
        return pool


def get_omop_connection(host: str, port: int, dbname: str, user: str, password: str):
    """
    Get a psycopg2 connection from the pool for an OMOP CDM database.
    Caller MUST return it via return_omop_connection() or conn.close().
    """
    pool = _get_pool(host, port, dbname, user, password)
    conn = pool.getconn()
    conn.autocommit = False
    return conn


def return_omop_connection(host: str, port: int, dbname: str, user: str, conn):
    """Return a connection to its pool."""
    key = (host, port, dbname, user)
    pool = _pools.get(key)
    if pool and not pool.closed:
        try:
            pool.putconn(conn)
        except Exception:
            logger.warning("Failed to return connection to pool, closing it")
            try:
                conn.close()
            except Exception:
                pass
    else:
        try:
            conn.close()
        except Exception:
            pass


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
