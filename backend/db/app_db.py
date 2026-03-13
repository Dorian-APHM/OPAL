"""
Application database connection and session management.
Uses PostgreSQL for storing CDM configs, snapshots, and analysis results.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from config import DATABASE_URL, APP_DB_POOL_SIZE, APP_DB_MAX_OVERFLOW, APP_DB_POOL_RECYCLE

_engine_kwargs = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs.update(
        pool_size=APP_DB_POOL_SIZE,
        max_overflow=APP_DB_MAX_OVERFLOW,
        pool_recycle=APP_DB_POOL_RECYCLE,
    )
engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
