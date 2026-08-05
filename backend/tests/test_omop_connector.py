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


def _entry_with_pool(pool):
    e = PoolEntry(pool, "pw")
    return e


def test_close_returns_connection_to_pool():
    pool = MagicMock()
    raw = MagicMock()
    wrapper = PooledConnection(raw, _entry_with_pool(pool), "k")
    wrapper.close()
    pool.putconn.assert_called_once_with(raw, close=False)


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


def test_checkout_increments_in_use_and_close_decrements(monkeypatch):
    pool = MagicMock()
    raw = MagicMock()
    pool.getconn.return_value = raw

    host, port, db_, user, pw = "h2", 5432, "d2", "u2", "pw"
    key = _pool_key(host, port, db_, user)
    entry = _entry_with_pool(pool)
    monkeypatch.setitem(oc._pools, key, entry)

    conn = get_omop_connection(host, port, db_, user, pw)
    assert entry.in_use == 1
    conn.close()
    assert entry.in_use == 0


def test_evict_skips_pool_with_checked_out_connection(monkeypatch):
    """A pool whose connection is held by a long batch must never be evicted,
    even when last_used is far past the idle timeout (regression: eviction
    used to closeall() mid-query and kill the running analysis)."""
    busy = _entry_with_pool(MagicMock())
    busy.in_use = 1
    busy.last_used = 0.0  # ancient — far past any idle timeout

    idle = _entry_with_pool(MagicMock())
    idle.in_use = 0
    idle.last_used = 0.0

    monkeypatch.setitem(oc._pools, "busy_cdm", busy)
    monkeypatch.setitem(oc._pools, "idle_cdm", idle)

    oc.evict_idle_pools()

    assert "busy_cdm" in oc._pools
    busy.pool.closeall.assert_not_called()
    assert "idle_cdm" not in oc._pools
    idle.pool.closeall.assert_called_once()
