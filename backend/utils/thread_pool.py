"""Bounded thread pool for background tasks (quality, mapping, extraction, etc.).

All modules should use ``submit_task(fn, *args)`` instead of spawning raw
``threading.Thread`` instances.  This prevents unbounded thread creation under
concurrent load (P20 fix).
"""
from concurrent.futures import ThreadPoolExecutor

from config import MAX_WORKER_THREADS

executor = ThreadPoolExecutor(max_workers=MAX_WORKER_THREADS, thread_name_prefix="opal-worker")


def submit_task(fn, *args, **kwargs):
    """Submit a callable to the shared thread pool. Returns a Future."""
    return executor.submit(fn, *args, **kwargs)
