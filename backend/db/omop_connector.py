"""
Dynamic connection to external OMOP CDM PostgreSQL databases.

Uses a per-CDM ThreadedConnectionPool to reuse TCP connections and avoid
the ~50-100ms handshake overhead on every API call.  Each pool is keyed
by (host, port, dbname, user).  Connections are returned to the pool on
close() — callers keep using the same try/finally: conn.close() pattern.
"""
import hashlib
import logging
import threading
import time

import psycopg2
from psycopg2.extras import DictCursor
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
from config import OMOP_POOL_MIN_CONN, OMOP_POOL_MAX_CONN, OMOP_POOL_IDLE_TIMEOUT, OMOP_STATEMENT_TIMEOUT_MS

STATEMENT_TIMEOUT_MS = OMOP_STATEMENT_TIMEOUT_MS
POOL_MIN_CONN = OMOP_POOL_MIN_CONN     # minimum idle connections per CDM
POOL_MAX_CONN = OMOP_POOL_MAX_CONN     # maximum connections per CDM
POOL_IDLE_TIMEOUT = OMOP_POOL_IDLE_TIMEOUT  # seconds – evict unused pools

# ---------------------------------------------------------------------------
# Pool registry   (protected by _pools_lock)
# ---------------------------------------------------------------------------
_pools: dict[str, "PoolEntry"] = {}
_pools_lock = threading.Lock()


def _hash_password(password: str) -> str:
    """Return a SHA-256 hex digest of the password for safe comparison.

    The plaintext password is never stored in the pool entry; only the
    digest is kept so we can detect credential changes without retaining
    the secret in memory any longer than necessary (S11).
    """
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


class PoolEntry:
    """Holds a pool together with its creation metadata."""

    __slots__ = ("pool", "password_hash", "last_used")

    def __init__(self, pool: ThreadedConnectionPool, password: str):
        self.pool = pool
        # Store only the SHA-256 hash — never the plaintext password (S11).
        self.password_hash = _hash_password(password)
        self.last_used = time.monotonic()

    def touch(self):
        self.last_used = time.monotonic()


# ---------------------------------------------------------------------------
# PooledConnection wrapper
# ---------------------------------------------------------------------------
class PooledConnection:
    """
    Thin proxy around a raw psycopg2 connection.

    * ``close()`` returns the connection to the pool instead of closing it.
    * Every other attribute/method is forwarded transparently.
    * Works as a context manager (``with get_omop_connection(...) as conn:``).
    """

    __slots__ = ("_conn", "_pool_entry", "_pool_key", "_closed")

    def __init__(self, conn, pool_entry: PoolEntry, pool_key: str):
        self._conn = conn
        self._pool_entry = pool_entry
        self._pool_key = pool_key
        self._closed = False

    # -- proxy all attribute access to the real connection -----------------
    def __getattr__(self, name):
        return getattr(self._conn, name)

    # -- close → return to pool --------------------------------------------
    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._conn.rollback()           # clean session state
            # A caller may have changed session GUCs for a long-running op (e.g.
            # `SET statement_timeout = 0` during cache / SapBERT builds). Restore
            # the configured default so the next borrower of this pooled
            # connection doesn't inherit the leaked value. SET is transactional,
            # so commit it (no-op under autocommit).
            with self._conn.cursor() as cur:
                cur.execute("SET statement_timeout = %s", (STATEMENT_TIMEOUT_MS,))
            self._conn.commit()
        except Exception:
            # connection is broken – discard it
            try:
                self._pool_entry.pool.putconn(self._conn, close=True)
            except Exception:
                pass
            return
        try:
            self._pool_entry.pool.putconn(self._conn)
        except Exception:
            pass

    # -- context manager ---------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    # -- cursor convenience (keeps DictCursor default easy) ----------------
    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    # -- make sure the connection is returned if the wrapper is GC'd -------
    def __del__(self):
        # Reaching __del__ without an explicit close() means a caller forgot the
        # try/finally (a connection leak). Surface it as a warning instead of
        # silently relying on the garbage collector — which may also run on a
        # different thread — then best-effort return the connection to the pool.
        if not self._closed:
            try:
                logger.warning(
                    "PooledConnection for %s was garbage-collected without an explicit "
                    "close() — likely a missing try/finally (connection leak).",
                    self._pool_key,
                )
            except Exception:
                pass
        self.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def _pool_key(host: str, port: int, dbname: str, user: str) -> str:
    return f"{host}:{port}/{dbname}@{user}"


def _create_pool(host, port, dbname, user, password, sslmode=None) -> ThreadedConnectionPool:
    kwargs = dict(
        minconn=POOL_MIN_CONN,
        maxconn=POOL_MAX_CONN,
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        connect_timeout=10,
        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
    )
    if sslmode:
        kwargs["sslmode"] = sslmode
    return ThreadedConnectionPool(**kwargs)


def get_omop_connection(host: str, port: int, dbname: str, user: str, password: str, sslmode: str | None = None):
    """
    Obtain a connection from the per-CDM pool.

    Returns a ``PooledConnection`` that behaves exactly like a psycopg2
    connection.  Callers MUST call ``conn.close()`` in a ``finally`` block
    (or use ``with``).  ``close()`` returns the connection to the pool.
    """
    key = _pool_key(host, port, dbname, user)

    with _pools_lock:
        entry = _pools.get(key)
        # Invalidate pool if password changed (compare hashes, not plaintext — S11)
        if entry is not None and entry.password_hash != _hash_password(password):
            logger.info("CDM password changed for %s – recreating pool", key)
            try:
                entry.pool.closeall()
            except Exception:
                pass
            entry = None

        if entry is None:
            pool = _create_pool(host, port, dbname, user, password, sslmode=sslmode)
            entry = PoolEntry(pool, password)
            _pools[key] = entry
            logger.info("Created connection pool for CDM %s", key)

    entry.touch()

    try:
        conn = entry.pool.getconn()
    except psycopg2.pool.PoolError:
        # Pool exhausted – raise a clear error
        raise ConnectionError(
            f"Connection pool exhausted for CDM {key} "
            f"(max {POOL_MAX_CONN} connections). Try again shortly."
        )

    # Ensure a clean state (no stale transaction from previous use)
    try:
        conn.rollback()
    except Exception:
        # Dead connection – discard and get a fresh one. The replacement getconn
        # must also translate pool exhaustion into a clean ConnectionError instead
        # of leaking a raw PoolError.
        try:
            entry.pool.putconn(conn, close=True)
        except Exception:
            pass
        try:
            conn = entry.pool.getconn()
        except psycopg2.pool.PoolError:
            raise ConnectionError(
                f"Connection pool exhausted for CDM {key} "
                f"(max {POOL_MAX_CONN} connections). Try again shortly."
            )

    conn.autocommit = False
    return PooledConnection(conn, entry, key)


def test_omop_connection(host: str, port: int, dbname: str, user: str, password: str, sslmode: str | None = None) -> dict:
    """
    Test connectivity to an OMOP CDM database.
    Uses a direct (non-pooled) connection — we don't want to create a
    pool just for a one-off connectivity test.
    """
    try:
        kwargs = dict(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            connect_timeout=10,
        )
        if sslmode:
            kwargs["sslmode"] = sslmode
        conn = psycopg2.connect(**kwargs)
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT 1")
        conn.close()
        return {"success": True, "message": "Connection successful"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ---------------------------------------------------------------------------
# Pool lifecycle management
# ---------------------------------------------------------------------------
def invalidate_pool(host: str, port: int, dbname: str, user: str):
    """
    Close and remove the pool for a specific CDM.
    Call this when CDM credentials are updated or a CDM is deleted.
    """
    key = _pool_key(host, port, dbname, user)
    with _pools_lock:
        entry = _pools.pop(key, None)
    if entry:
        try:
            entry.pool.closeall()
        except Exception:
            pass
        logger.info("Invalidated connection pool for CDM %s", key)


def evict_idle_pools():
    """Close pools that have not been used for POOL_IDLE_TIMEOUT seconds."""
    now = time.monotonic()
    to_evict = []
    with _pools_lock:
        for key, entry in list(_pools.items()):
            if now - entry.last_used > POOL_IDLE_TIMEOUT:
                to_evict.append(_pools.pop(key))
    for entry in to_evict:
        try:
            entry.pool.closeall()
        except Exception:
            pass
    if to_evict:
        logger.info("Evicted %d idle connection pool(s)", len(to_evict))


def close_all_pools():
    """Shutdown hook — close every pool."""
    with _pools_lock:
        for entry in _pools.values():
            try:
                entry.pool.closeall()
            except Exception:
                pass
        _pools.clear()
    logger.info("All OMOP connection pools closed")
