"""Tests for utils/thread_pool.py — Bounded thread pool for background tasks."""
import time
import threading
from concurrent.futures import Future

from utils.thread_pool import executor, submit_task


class TestSubmitTask:
    """Test submit_task() dispatches work correctly."""

    def test_returns_future(self):
        future = submit_task(lambda: 42)
        assert isinstance(future, Future)
        assert future.result(timeout=5) == 42

    def test_passes_args(self):
        def add(a, b):
            return a + b
        assert submit_task(add, 3, 4).result(timeout=5) == 7

    def test_passes_kwargs(self):
        def greet(name="world"):
            return f"hello {name}"
        assert submit_task(greet, name="opal").result(timeout=5) == "hello opal"

    def test_exception_propagated(self):
        def boom():
            raise ValueError("bang")
        future = submit_task(boom)
        try:
            future.result(timeout=5)
            assert False, "Should have raised"
        except ValueError as e:
            assert "bang" in str(e)

    def test_runs_in_worker_thread(self):
        """Task should run in a thread named 'opal-worker-*', not the main thread."""
        future = submit_task(threading.current_thread().name.__class__, threading.current_thread())
        # Just verify it doesn't run on the test thread
        main_name = threading.current_thread().name
        def get_thread_name():
            return threading.current_thread().name
        name = submit_task(get_thread_name).result(timeout=5)
        assert name != main_name
        assert "opal-worker" in name


class TestExecutorConfig:
    """Test executor is properly configured."""

    def test_max_workers_bounded(self):
        assert executor._max_workers <= 64  # reasonable upper bound

    def test_thread_name_prefix(self):
        assert executor._thread_name_prefix == "opal-worker"

    def test_concurrent_tasks(self):
        """Multiple tasks can run concurrently."""
        results = []
        barrier = threading.Barrier(3, timeout=10)

        def worker(idx):
            barrier.wait()
            results.append(idx)
            return idx

        futures = [submit_task(worker, i) for i in range(3)]
        for f in futures:
            f.result(timeout=10)
        assert sorted(results) == [0, 1, 2]
