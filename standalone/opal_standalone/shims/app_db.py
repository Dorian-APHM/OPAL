"""Standalone replacement for ``backend/db/app_db.py``.

There is no application database in standalone mode. A couple of engines open a
session opportunistically (only to enrich labels from reference codebooks); they
get this inert session instead, so no SQLAlchemy dependency and no connection
are ever needed.
"""
from __future__ import annotations


class _NullSession:
    """A session that accepts the calls the engines make and does nothing."""

    def close(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def add(self, _obj) -> None:
        return None

    def query(self, *_args, **_kwargs):
        raise RuntimeError(
            "No application database in standalone mode — persistence goes "
            "through opal_standalone.store (SQLite)."
        )


def SessionLocal() -> _NullSession:  # noqa: N802 - mirrors the backend name
    return _NullSession()


def get_db():  # pragma: no cover - FastAPI dependency, unused here
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


engine = None
Base = None
