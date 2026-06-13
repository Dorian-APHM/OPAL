"""
Tests for the pooled OMOP connection wrapper.

Regression coverage for:
- close() returns the connection to the pool and is idempotent;
- a wrapper garbage-collected without close() logs a leak warning (instead of a
  silent return);
- get_omop_connection translates pool exhaustion on the dead-connection retry
  path into a clean ConnectionError (not a raw PoolError).
"""
import logging
from unittest.mock import MagicMock

import psycopg2.pool
import pytest

import db.omop_connector as oc
from db.omop_connector import PooledConnection, PoolEntry, get_omop_connection, _pool_key
from db.dialects import get_dialect


def _entry_with_pool(pool):
    e = PoolEntry(pool, "pw", get_dialect("postgresql"))
    return e


def test_close_returns_connection_to_pool():
    pool = MagicMock()
    raw = MagicMock()
    wrapper = PooledConnection(raw, _entry_with_pool(pool), "k")
    wrapper.close()
    pool.putconn.assert_called_once_with(raw)


def test_close_is_idempotent():
    pool = MagicMock()
    raw = MagicMock()
    wrapper = PooledConnection(raw, _entry_with_pool(pool), "k")
    wrapper.close()
    wrapper.close()
    assert pool.putconn.call_count == 1


def test_del_without_close_logs_leak_warning(caplog):
    pool = MagicMock()
    raw = MagicMock()
    wrapper = PooledConnection(raw, _entry_with_pool(pool), "leaky_cdm")
    with caplog.at_level(logging.WARNING, logger="db.omop_connector"):
        wrapper.__del__()  # simulate garbage collection
    assert any("without an explicit close" in r.message or "leak" in r.message.lower()
               for r in caplog.records)
    # Still best-effort returned to the pool.
    pool.putconn.assert_called_once()


def test_retry_getconn_pool_exhaustion_raises_connectionerror(monkeypatch):
    """When the first borrowed connection is dead and the pool is then exhausted,
    the caller must see a ConnectionError, not a raw psycopg2 PoolError."""
    class FakePool:
        def __init__(self):
            self.getconn_calls = 0
            self.put_closed = []

        def getconn(self):
            self.getconn_calls += 1
            if self.getconn_calls == 1:
                dead = MagicMock()
                dead.rollback.side_effect = Exception("dead connection")
                return dead
            raise psycopg2.pool.PoolError("connection pool exhausted")

        def putconn(self, conn, close=False):
            self.put_closed.append(close)

    host, port, db_, user, pw = "h", 5432, "d", "u", "pw"
    key = _pool_key(host, port, db_, user)
    monkeypatch.setitem(oc._pools, key, _entry_with_pool(FakePool()))

    with pytest.raises(ConnectionError):
        get_omop_connection(host, port, db_, user, pw)
