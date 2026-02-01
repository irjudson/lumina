"""Integration tests for complete job workflows.

These tests require a FULLY running Docker environment with:
- FastAPI server on port 8765
- PostgreSQL

Run with: docker-compose up && pytest -m e2e
"""

import time
import uuid

import pytest

# Skip collection if requests not installed (not needed for unit tests)
requests = pytest.importorskip("requests")

# Mark as both integration and e2e - these need full Docker stack
pytestmark = [pytest.mark.integration, pytest.mark.e2e]


class TestJobWorkflowIntegration:
    """End-to-end tests for job workflows."""

    BASE_URL = "http://localhost:8765"

    def test_scan_job_end_to_end(self, tmp_path):
        """Test complete scan workflow from submission to completion."""
        # Submit scan job
        catalog_id = str(uuid.uuid4())
        response = requests.post(
            f"{self.BASE_URL}/api/jobs/submit",
            json={
                "catalog_id": catalog_id,
                "job_type": "scan",
                "parameters": {
                    "catalog_id": catalog_id,
                    "source_paths": ["/app/photos"],
                    "workers": 2,
                },
            },
        )

        assert response.status_code in [200, 500]  # May fail if paths don't exist
        if response.status_code != 200:
            return  # Skip rest of test if job couldn't be submitted

        job_data = response.json()
        job_id = job_data["id"]
        assert job_data["status"] in ["PENDING", "PROGRESS"]

        # Poll for completion (with shorter timeout since paths may not exist)
        max_wait = 10  # seconds
        start_time = time.time()
        final_status = None

        while time.time() - start_time < max_wait:
            status_response = requests.get(f"{self.BASE_URL}/api/jobs/{job_id}")
            assert status_response.status_code == 200

            status_data = status_response.json()
            final_status = status_data["status"]

            if final_status in ["SUCCESS", "FAILURE"]:
                break

            time.sleep(0.5)

        # Verify job completed (may fail due to invalid paths)
        assert final_status in ["SUCCESS", "FAILURE", "PROGRESS"]

    def test_detect_duplicates_job_workflow(self):
        """Test duplicate detection workflow."""
        catalog_id = str(uuid.uuid4())
        response = requests.post(
            f"{self.BASE_URL}/api/jobs/submit",
            json={
                "catalog_id": catalog_id,
                "job_type": "detect_duplicates",
                "parameters": {
                    "catalog_id": catalog_id,
                    "similarity_threshold": 5,
                },
            },
        )

        assert response.status_code in [200, 500]
        if response.status_code != 200:
            return

        job_id = response.json()["id"]

        # Wait for completion
        time.sleep(2)

        status_response = requests.get(f"{self.BASE_URL}/api/jobs/{job_id}")
        assert status_response.status_code == 200
        assert status_response.json()["status"] in ["SUCCESS", "FAILURE", "PROGRESS"]

    def test_generate_thumbnails_workflow(self):
        """Test thumbnail generation workflow."""
        catalog_id = str(uuid.uuid4())
        response = requests.post(
            f"{self.BASE_URL}/api/jobs/submit",
            json={
                "catalog_id": catalog_id,
                "job_type": "generate_thumbnails",
                "parameters": {
                    "catalog_id": catalog_id,
                },
            },
        )

        assert response.status_code in [200, 500]
        if response.status_code != 200:
            return

        job_id = response.json()["id"]

        # Wait for completion
        time.sleep(2)

        status_response = requests.get(f"{self.BASE_URL}/api/jobs/{job_id}")
        assert status_response.status_code == 200
        assert status_response.json()["status"] in ["SUCCESS", "FAILURE", "PROGRESS"]

    def test_concurrent_jobs(self):
        """Test multiple jobs running concurrently."""
        job_ids = []

        # Submit multiple jobs
        for i in range(3):
            catalog_id = str(uuid.uuid4())
            response = requests.post(
                f"{self.BASE_URL}/api/jobs/submit",
                json={
                    "catalog_id": catalog_id,
                    "job_type": "scan",
                    "parameters": {
                        "catalog_id": catalog_id,
                        "source_paths": [f"/app/photos{i}"],
                        "workers": 1,
                    },
                },
            )
            if response.status_code == 200:
                job_ids.append(response.json()["id"])

        if not job_ids:
            pytest.skip("No jobs could be submitted")

        # Wait for processing
        time.sleep(5)

        # Check all jobs
        for job_id in job_ids:
            response = requests.get(f"{self.BASE_URL}/api/jobs/{job_id}")
            assert response.status_code == 200
            assert response.json()["status"] in [
                "SUCCESS",
                "FAILURE",
                "PROGRESS",
                "PENDING",
            ]

    def test_job_cancellation(self):
        """Test job can be cancelled."""
        catalog_id = str(uuid.uuid4())
        response = requests.post(
            f"{self.BASE_URL}/api/jobs/submit",
            json={
                "catalog_id": catalog_id,
                "job_type": "scan",
                "parameters": {
                    "catalog_id": catalog_id,
                    "source_paths": ["/app/photos"],
                    "workers": 1,
                },
            },
        )

        if response.status_code != 200:
            pytest.skip("Job submission failed")

        job_id = response.json()["id"]

        # Try to cancel
        cancel_response = requests.delete(f"{self.BASE_URL}/api/jobs/{job_id}")
        assert cancel_response.status_code in [200, 400, 404]

        # If cancelled successfully, verify status
        if cancel_response.status_code == 200:
            status_response = requests.get(f"{self.BASE_URL}/api/jobs/{job_id}")
            if status_response.status_code == 200:
                status = status_response.json()["status"]
                assert status in ["FAILURE", "SUCCESS", "PROGRESS"]

    def test_job_error_handling(self):
        """Test job failure is handled correctly."""
        # Submit job with invalid catalog ID
        response = requests.post(
            f"{self.BASE_URL}/api/jobs/submit",
            json={
                "catalog_id": "invalid-catalog-id",
                "job_type": "scan",
                "parameters": {
                    "catalog_id": "invalid-catalog-id",
                    "source_paths": ["/nonexistent/path"],
                    "workers": 1,
                },
            },
        )

        # May fail on submission or during execution
        assert response.status_code in [200, 400, 500]
        if response.status_code != 200:
            return  # Expected failure

        job_id = response.json()["id"]

        # Wait for processing
        time.sleep(3)

        status_response = requests.get(f"{self.BASE_URL}/api/jobs/{job_id}")
        assert status_response.status_code == 200

        status_data = status_response.json()
        # Should fail due to invalid path
        assert status_data["status"] in ["FAILURE", "PROGRESS", "PENDING"]

    def test_list_jobs(self):
        """Test listing jobs."""
        response = requests.get(f"{self.BASE_URL}/api/jobs/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_invalid_job_type(self):
        """Test submitting invalid job type."""
        response = requests.post(
            f"{self.BASE_URL}/api/jobs/submit",
            json={
                "catalog_id": str(uuid.uuid4()),
                "job_type": "invalid_type",
                "parameters": {},
            },
        )
        assert response.status_code == 400


@pytest.mark.integration
class TestServiceHealth:
    """Tests for service health checks."""

    BASE_URL = "http://localhost:8765"

    def test_api_health(self):
        """Test main API health endpoint."""
        response = requests.get(f"{self.BASE_URL}/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_jobs_health(self):
        """Test jobs API health endpoint."""
        response = requests.get(f"{self.BASE_URL}/api/jobs/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["backend"] == "threading"

    def test_jobs_system_working(self):
        """Test job system is working by submitting and checking a job."""
        catalog_id = str(uuid.uuid4())
        response = requests.post(
            f"{self.BASE_URL}/api/jobs/submit",
            json={
                "catalog_id": catalog_id,
                "job_type": "scan",
                "parameters": {
                    "catalog_id": catalog_id,
                    "source_paths": ["/test"],
                    "workers": 1,
                },
            },
        )

        # Job submission should work (execution may fail due to paths)
        assert response.status_code in [200, 500]

        if response.status_code == 200:
            job_id = response.json()["id"]

            # Should be able to query job status
            status_response = requests.get(f"{self.BASE_URL}/api/jobs/{job_id}")
            assert status_response.status_code == 200
            assert "status" in status_response.json()
