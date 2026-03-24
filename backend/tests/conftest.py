"""
Shared test fixtures for all backend tests.
Uses SQLite in-memory (StaticPool) so all connections share the same database.
"""
import os
import pytest

# Override DATABASE_URL before importing any app modules
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["TESTING"] = "1"
os.environ["AUTH_ENABLED"] = "false"

from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import Base
import db.app_db as _app_db
from main import app

# Replace the app engine with an in-memory SQLite using StaticPool
# so that all connections (TestClient + dependency) share the same DB.
test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_app_db.engine = test_engine


class _FakeAuthMiddleware(BaseHTTPMiddleware):
    """Inject a test user for tests. Defaults to admin role.

    Use X-Test-Roles header to override roles (comma-separated).
    Use X-Test-Username header to override username.
    """
    async def dispatch(self, request, call_next):
        roles_header = request.headers.get("X-Test-Roles")
        username_header = request.headers.get("X-Test-Username")
        roles = roles_header.split(",") if roles_header else ["admin"]
        username = username_header or "testuser"
        request.state.user = {"sub": username, "preferred_username": username, "roles": roles}
        return await call_next(request)

app.add_middleware(_FakeAuthMiddleware)

TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[_app_db.get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    """Create all tables before each test, drop after."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    return TestClient(app)
