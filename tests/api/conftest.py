"""Pytest configuration for API tests."""

import uuid

import pytest
from fastapi.testclient import TestClient

from lumina.db.models import Catalog


@pytest.fixture
def test_catalog_id(db_session) -> uuid.UUID:
    """Create a test catalog and return its ID for FK constraint satisfaction."""
    catalog = Catalog(
        id=uuid.uuid4(),
        name="API Test Catalog",
        schema_name=f"test_api_{uuid.uuid4().hex[:8]}",
        source_directories=["/test/api/path"],
    )
    db_session.add(catalog)
    db_session.commit()
    db_session.refresh(catalog)
    return catalog.id


@pytest.fixture
def client(db_session):
    """Create a test client for the FastAPI application."""
    from lumina.api.app import app
    from lumina.db import get_db

    # Override the get_db dependency to use our test database session
    def override_get_db():
        try:
            yield db_session
        finally:
            pass  # db_session cleanup is handled by the fixture

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    # Cleanup
    app.dependency_overrides.clear()
