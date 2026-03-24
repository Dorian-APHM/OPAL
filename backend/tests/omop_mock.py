"""
Reusable OMOP connection mock helper for tests.

Provides a mock psycopg2 connection with DictCursor-like behavior,
allowing unit testing of modules that query external OMOP CDM databases.

Usage:
    from tests.omop_mock import make_omop_conn

    conn = make_omop_conn([
        {"total": 100},                    # first fetchone() returns {"total": 100}
        [{"id": 1}, {"id": 2}],            # first fetchall() returns list of dicts
    ])
"""
from unittest.mock import MagicMock, patch


class DictRow(dict):
    """A dict subclass that mimics psycopg2 DictRow (supports both key and index access)."""
    pass


class MockCursor:
    """
    Mock cursor that replays pre-configured responses.

    Responses is a list where each entry corresponds to one execute() call.
    Each entry can be:
    - A dict: returned by fetchone()
    - A list of dicts: returned by fetchall()
    - An Exception: raised on execute()
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self._call_idx = 0
        self._current = None
        self.description = [("col",)]
        self.rowcount = 0

    def execute(self, query, params=None):
        if self._call_idx < len(self._responses):
            resp = self._responses[self._call_idx]
            if isinstance(resp, Exception):
                self._call_idx += 1
                raise resp
            self._current = resp
            self._call_idx += 1
        else:
            self._current = None

    def fetchone(self):
        if self._current is None:
            return None
        if isinstance(self._current, dict):
            return DictRow(self._current)
        if isinstance(self._current, list) and len(self._current) > 0:
            return DictRow(self._current[0])
        return None

    def fetchall(self):
        if self._current is None:
            return []
        if isinstance(self._current, list):
            return [DictRow(r) for r in self._current]
        if isinstance(self._current, dict):
            return [DictRow(self._current)]
        return []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def make_omop_conn(responses=None):
    """
    Create a mock psycopg2 connection.

    Parameters
    ----------
    responses : list
        Each entry corresponds to one cursor.execute() call, in order.
        Entries can be:
        - dict: returned by fetchone()
        - list[dict]: returned by fetchall()
        - Exception: raised on execute()

    Returns
    -------
    MagicMock
        A mock connection object with cursor() returning a MockCursor.
    """
    if responses is None:
        responses = []

    conn = MagicMock()
    cursor = MockCursor(responses)

    # Support both conn.cursor() and conn.cursor(cursor_factory=...)
    conn.cursor.return_value = cursor
    conn.rollback = MagicMock()
    conn.close = MagicMock()

    return conn
