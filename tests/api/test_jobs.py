"""Tests for jobs API router endpoints.

All tests require database connection.
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from lumina.db.models import Job

pytestmark = pytest.mark.integration


def unique_job_id(prefix: str = "test-job") -> str:
    """Generate a unique job ID for test isolation."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _create_test_job(
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


def test_health_endpoint(client: TestClient):
    """Test jobs health endpoint."""
    response = client.get("/api/jobs/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["backend"] == "threading"


def test_get_job_success(client: TestClient, db_session):
    """Test getting a completed job."""
    job_id = unique_job_id("success")
    _create_test_job(
        db_session,
        job_id,
        status="SUCCESS",
        result={"files_processed": 100, "files_added": 50},
    )

    response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == job_id
    assert data["status"] == "success"
    assert data["result"]["files_processed"] == 100
    assert data["result"]["files_added"] == 50


def test_get_job_progress(client: TestClient, db_session):
    """Test getting an in-progress job."""
    job_id = unique_job_id("progress")
    _create_test_job(
        db_session,
        job_id,
        status="PROGRESS",
        progress={"current": 50, "total": 100, "percent": 50},
    )

    response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == job_id
    assert data["status"] == "running"
    assert data["progress"]["current"] == 50
    assert data["progress"]["total"] == 100
    assert data["progress"]["percent"] == 50


def test_get_job_failure(client: TestClient, db_session):
    """Test getting a failed job."""
    job_id = unique_job_id("failure")
    _create_test_job(
        db_session, job_id, status="FAILURE", error="Task failed due to error"
    )

    response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == job_id
    assert data["status"] == "failure"
    assert data["error"] == "Task failed due to error"


def test_get_job_not_found(client: TestClient):
    """Test getting a non-existent job."""
    response = client.get("/api/jobs/nonexistent-job-id")
    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"].lower()


def test_list_jobs_empty(client: TestClient):
    """Test listing jobs when none exist."""
    response = client.get("/api/jobs/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # May have other jobs from other tests due to shared DB


def test_list_jobs_with_jobs(client: TestClient, db_session):
    """Test listing jobs."""
    job_id1 = unique_job_id("list1")
    job_id2 = unique_job_id("list2")

    _create_test_job(db_session, job_id1, status="SUCCESS")
    _create_test_job(db_session, job_id2, status="PROGRESS")

    response = client.get("/api/jobs/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

    # Find our test jobs in the list
    job_ids = [job["id"] for job in data]
    assert job_id1 in job_ids
    assert job_id2 in job_ids


def test_cancel_job_pending(client: TestClient, db_session):
    """Test canceling a pending job."""
    job_id = unique_job_id("cancel")
    _create_test_job(db_session, job_id, status="PENDING")

    response = client.delete(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    data = response.json()
    assert "cancelled" in data["message"].lower()

    # Verify job was marked as failed
    db_session.expire_all()
    job = db_session.query(Job).filter(Job.id == job_id).first()
    assert job.status == "FAILURE"
    assert "Cancelled" in job.error


def test_cancel_job_completed(client: TestClient, db_session):
    """Test attempting to cancel a completed job."""
    job_id = unique_job_id("completed")
    _create_test_job(db_session, job_id, status="SUCCESS")

    response = client.delete(f"/api/jobs/{job_id}")

    assert response.status_code == 400
    data = response.json()
    assert "cannot cancel" in data["detail"].lower()


def test_cancel_job_not_found(client: TestClient):
    """Test canceling a non-existent job."""
    response = client.delete("/api/jobs/nonexistent-job-id")
    assert response.status_code == 404


@patch("lumina.jobs.background_jobs.run_job_in_background")
def test_submit_job(mock_run_job, client: TestClient, db_session, test_catalog_id):
    """Test submitting a new job."""
    mock_run_job.return_value = None

    response = client.post(
        "/api/jobs/submit",
        json={
            "catalog_id": str(test_catalog_id),
            "job_type": "scan",
            "parameters": {
                "catalog_id": str(test_catalog_id),
                "source_paths": ["/test/path"],
                "workers": 4,
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["status"] == "pending"

    # Verify job was created in database
    job = db_session.query(Job).filter(Job.id == data["id"]).first()
    assert job is not None
    assert job.job_type == "scan"
    assert job.status == "PENDING"


def test_submit_job_invalid_type(client: TestClient, test_catalog_id):
    """Test submitting a job with invalid type."""
    response = client.post(
        "/api/jobs/submit",
        json={
            "catalog_id": str(test_catalog_id),
            "job_type": "invalid_job_type",
            "parameters": {},
        },
    )

    assert response.status_code == 400
    data = response.json()
    assert "unknown job type" in data["detail"].lower()
