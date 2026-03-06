"""
Shared test fixtures for all backend tests.
Uses a single SQLite test database with proper dependency override.
"""
import os
import pytest

# Override DATABASE_URL before importing any app modules
os.environ["DATABASE_URL"] = "sqlite:///./test_opal.db"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base
from db.app_db import get_db
from main import app

# Single test engine shared across all test files
test_engine = create_engine(
    "sqlite:///./test_opal.db",
    connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    """Create all tables before each test, drop after."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    return TestClient(app)
