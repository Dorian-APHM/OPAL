"""Tests for the LRU-style concept cache in modules/concept/router.py."""
import time
import threading
from unittest.mock import patch

from modules.concept.router import _cache_get, _cache_set, _concept_cache, _concept_cache_lock, _CACHE_TTL, _CACHE_MAX_SIZE


import pytest


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the concept cache before and after each test."""
    with _concept_cache_lock:
        _concept_cache.clear()
    yield
    with _concept_cache_lock:
        _concept_cache.clear()


def test_cache_set_and_get():
    key = ("details", "cdm1", 42)
    data = {"concept": {"concept_id": 42, "concept_name": "Test"}}
    _cache_set(key, data)
    assert _cache_get(key) == data


def test_cache_miss():
    assert _cache_get(("details", "cdm1", 999)) is None


def test_cache_ttl_expiry():
    """Entries older than _CACHE_TTL should be evicted on get."""
    key = ("details", "cdm1", 1)
    data = {"concept": {"concept_id": 1}}

    # Manually insert an entry with an old timestamp
    with _concept_cache_lock:
        _concept_cache[key] = (time.monotonic() - _CACHE_TTL - 1, data)

    # Should return None because it's expired
    assert _cache_get(key) is None
    # Entry should be deleted
    assert key not in _concept_cache


def test_cache_not_expired():
    """Entries within TTL should be returned."""
    key = ("hierarchy", "cdm1", 1)
    data = {"ancestors": []}

    with _concept_cache_lock:
        _concept_cache[key] = (time.monotonic(), data)

    assert _cache_get(key) == data


def test_cache_eviction_at_max_size():
    """When cache reaches _CACHE_MAX_SIZE, the oldest entry is evicted."""
    # Fill cache to max
    for i in range(_CACHE_MAX_SIZE):
        with _concept_cache_lock:
            _concept_cache[("test", i)] = (time.monotonic() + i * 0.001, {"id": i})

    assert len(_concept_cache) == _CACHE_MAX_SIZE

    # The entry with the smallest timestamp is ("test", 0)
    oldest_key = ("test", 0)
    assert oldest_key in _concept_cache

    # Adding one more should evict the oldest
    _cache_set(("test", "new"), {"id": "new"})
    assert len(_concept_cache) == _CACHE_MAX_SIZE
    assert oldest_key not in _concept_cache
    assert _cache_get(("test", "new")) == {"id": "new"}


def test_cache_different_keys():
    """Different keys should store different values."""
    _cache_set(("details", "cdm1", 1), {"type": "details"})
    _cache_set(("hierarchy", "cdm1", 1), {"type": "hierarchy"})

    assert _cache_get(("details", "cdm1", 1)) == {"type": "details"}
    assert _cache_get(("hierarchy", "cdm1", 1)) == {"type": "hierarchy"}


def test_cache_overwrite():
    """Setting the same key twice should overwrite."""
    key = ("details", "cdm1", 1)
    _cache_set(key, {"v": 1})
    _cache_set(key, {"v": 2})
    assert _cache_get(key) == {"v": 2}


def test_cache_thread_safety():
    """Concurrent reads and writes should not crash."""
    errors = []

    def writer(n):
        try:
            for i in range(50):
                _cache_set(("thread", n, i), {"n": n, "i": i})
        except Exception as e:
            errors.append(e)

    def reader(n):
        try:
            for i in range(50):
                _cache_get(("thread", n, i))
        except Exception as e:
            errors.append(e)

    threads = []
    for n in range(4):
        threads.append(threading.Thread(target=writer, args=(n,)))
        threads.append(threading.Thread(target=reader, args=(n,)))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread safety errors: {errors}"
