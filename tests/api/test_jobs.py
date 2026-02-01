"""Tests for jobs API router endpoints.

All tests require database connection.
"""

import uuid
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from lumina.db import get_db
from lumina.db.models import Job
from lumina.web.api import app

pytestmark = pytest.mark.integration


def unique_job_id(prefix: str = "test-job") -> str:
    """Generate a unique job ID for test isolation."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class TestJobEndpoints:
    """Tests for job API endpoints."""

    @pytest.fixture
    def client(self):
        """Create a test client for the FastAPI application."""
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

    def _create_test_job(
        self,
        db_session,
        job_id: str,
        status: str = "PENDING",
        progress: dict = None,
        result: dict = None,
        error: str = None,
    ):
        """Create a test job in the database."""
        job = Job(
            id=job_id,
            job_type="scan",
            status=status,
            parameters={},
            progress=progress,
            result=result,
            error=error,
        )
        db_session.add(job)
        db_session.commit()
        return job

    def test_health_endpoint(self, client):
        """Test jobs health endpoint."""
        response = client.get("/api/jobs/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["backend"] == "threading"

    def test_get_job_success(self, client, db_session):
        """Test getting a completed job."""
        job_id = unique_job_id("success")
        self._create_test_job(
            db_session,
            job_id,
            status="SUCCESS",
            result={"files_processed": 100, "files_added": 50},
        )

        response = client.get(f"/api/jobs/{job_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == job_id
        assert data["status"] == "SUCCESS"
        assert data["result"]["files_processed"] == 100
        assert data["result"]["files_added"] == 50

    def test_get_job_progress(self, client, db_session):
        """Test getting an in-progress job."""
        job_id = unique_job_id("progress")
        self._create_test_job(
            db_session,
            job_id,
            status="PROGRESS",
            progress={"current": 50, "total": 100, "percent": 50},
        )

        response = client.get(f"/api/jobs/{job_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == job_id
        assert data["status"] == "PROGRESS"
        assert data["progress"]["current"] == 50
        assert data["progress"]["total"] == 100
        assert data["progress"]["percent"] == 50

    def test_get_job_failure(self, client, db_session):
        """Test getting a failed job."""
        job_id = unique_job_id("failure")
        self._create_test_job(
            db_session, job_id, status="FAILURE", error="Task failed due to error"
        )

        response = client.get(f"/api/jobs/{job_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == job_id
        assert data["status"] == "FAILURE"
        assert data["error"] == "Task failed due to error"

    def test_get_job_not_found(self, client):
        """Test getting a non-existent job."""
        response = client.get("/api/jobs/nonexistent-job-id")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    def test_list_jobs_empty(self, client):
        """Test listing jobs when none exist."""
        response = client.get("/api/jobs/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # May have other jobs from other tests due to shared DB

    def test_list_jobs_with_jobs(self, client, db_session):
        """Test listing jobs."""
        job_id1 = unique_job_id("list1")
        job_id2 = unique_job_id("list2")

        self._create_test_job(db_session, job_id1, status="SUCCESS")
        self._create_test_job(db_session, job_id2, status="PROGRESS")

        response = client.get("/api/jobs/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Find our test jobs in the list
        job_ids = [job["id"] for job in data]
        assert job_id1 in job_ids
        assert job_id2 in job_ids

    def test_cancel_job_pending(self, client, db_session):
        """Test canceling a pending job."""
        job_id = unique_job_id("cancel")
        self._create_test_job(db_session, job_id, status="PENDING")

        response = client.delete(f"/api/jobs/{job_id}")

        assert response.status_code == 200
        data = response.json()
        assert "cancelled" in data["message"].lower()

        # Verify job was marked as failed
        db_session.expire_all()
        job = db_session.query(Job).filter(Job.id == job_id).first()
        assert job.status == "FAILURE"
        assert "Cancelled" in job.error

    def test_cancel_job_completed(self, client, db_session):
        """Test attempting to cancel a completed job."""
        job_id = unique_job_id("completed")
        self._create_test_job(db_session, job_id, status="SUCCESS")

        response = client.delete(f"/api/jobs/{job_id}")

        assert response.status_code == 400
        data = response.json()
        assert "cannot cancel" in data["detail"].lower()

    def test_cancel_job_not_found(self, client):
        """Test canceling a non-existent job."""
        response = client.delete("/api/jobs/nonexistent-job-id")
        assert response.status_code == 404

    @patch("lumina.jobs.background_jobs.run_job_in_background")
    def test_submit_job(self, mock_run_job, client, db_session):
        """Test submitting a new job."""
        # Mock the background job runner
        mock_run_job.return_value = None

        response = client.post(
            "/api/jobs/submit",
            json={
                "catalog_id": str(uuid.uuid4()),
                "job_type": "scan",
                "parameters": {
                    "catalog_id": str(uuid.uuid4()),
                    "source_paths": ["/test/path"],
                    "workers": 4,
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["status"] == "PENDING"

        # Verify job was created in database
        job = db_session.query(Job).filter(Job.id == data["id"]).first()
        assert job is not None
        assert job.job_type == "scan"
        assert job.status == "PENDING"

    def test_submit_job_invalid_type(self, client):
        """Test submitting a job with invalid type."""
        response = client.post(
            "/api/jobs/submit",
            json={
                "catalog_id": str(uuid.uuid4()),
                "job_type": "invalid_job_type",
                "parameters": {},
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "unknown job type" in data["detail"].lower()
