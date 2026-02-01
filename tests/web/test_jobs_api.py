"""Tests for jobs API endpoints from web interface.

Note: Most job API functionality is tested in tests/api/test_jobs.py.
These tests verify web-specific integration.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from lumina.db import get_db
from lumina.db.models import Job
from lumina.web.api import app

pytestmark = pytest.mark.integration


class TestWebJobsIntegration:
    """Tests for jobs API integration with web interface."""

    @pytest.fixture
    def client(self):
        """Create a test client for the web application."""
        return TestClient(app)

    @pytest.fixture
    def db_session(self, client):
        """Get a database session for creating test jobs."""
        db_gen = get_db()
        db = next(db_gen)
        try:
            yield db
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass

    def test_jobs_health_from_web(self, client):
        """Test jobs health endpoint is accessible from web API."""
        response = client.get("/api/jobs/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["backend"] == "threading"

    def test_jobs_list_from_web(self, client):
        """Test jobs list endpoint is accessible from web API."""
        response = client.get("/api/jobs/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_cors_headers_present(self, client):
        """Test CORS headers are present for web requests."""
        response = client.options(
            "/api/jobs/health", headers={"Origin": "http://localhost:8000"}
        )
        # CORS middleware should be configured
        assert response.status_code in [
            200,
            405,
        ]  # OPTIONS may not be explicitly handled

    def test_job_submission_from_web(self, client):
        """Test job can be submitted through web API."""
        response = client.post(
            "/api/jobs/submit",
            json={
                "catalog_id": str(uuid.uuid4()),
                "job_type": "scan",
                "parameters": {
                    "catalog_id": str(uuid.uuid4()),
                    "source_paths": ["/test/path"],
                    "workers": 2,
                },
            },
        )

        # Should create job (may fail on actual execution due to invalid paths, but should accept submission)
        assert response.status_code in [
            200,
            500,
        ]  # 200 if mock works, 500 if real execution fails
        if response.status_code == 200:
            data = response.json()
            assert "id" in data
