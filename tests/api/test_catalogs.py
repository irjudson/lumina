"""Tests for catalogs API router endpoints.

Tests for catalog-related endpoints including auto-tagging.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from lumina.db.models import Catalog

pytestmark = pytest.mark.integration


class TestAutoTagEndpoint:
    """Tests for POST /api/catalogs/{catalog_id}/auto-tag endpoint."""

    @patch("lumina.jobs.background_jobs.run_job_in_background")
    def test_start_auto_tag_success(self, mock_run_job, client, db_session):
        """Test starting an auto-tag job successfully."""
        # Create a real catalog in the test database
        catalog_id = uuid.uuid4()
        catalog = Catalog(
            id=catalog_id,
            name="Test Catalog",
            schema_name=f"catalog_{str(catalog_id).replace('-', '_')}",
            source_directories=["/tmp/test"],
        )
        db_session.add(catalog)
        db_session.commit()

        # Mock run_job_in_background to do nothing
        mock_run_job.return_value = None

        response = client.post(
            f"/api/catalogs/{catalog.id}/auto-tag",
            params={"backend": "openclip"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"
        assert "openclip" in data["message"]

        # Verify run_job_in_background was called
        assert mock_run_job.called

    @patch("lumina.jobs.background_jobs.run_job_in_background")
    def test_start_auto_tag_with_ollama(self, mock_run_job, client, db_session):
        """Test starting an auto-tag job with Ollama backend."""
        # Create a real catalog in the test database
        catalog_id = uuid.uuid4()
        catalog = Catalog(
            id=catalog_id,
            name="Ollama Test Catalog",
            schema_name=f"catalog_{str(catalog_id).replace('-', '_')}",
            source_directories=["/tmp/test"],
        )
        db_session.add(catalog)
        db_session.commit()

        # Mock run_job_in_background
        mock_run_job.return_value = None

        response = client.post(
            f"/api/catalogs/{catalog.id}/auto-tag",
            params={"backend": "ollama", "model": "llava"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "ollama" in data["message"]

        # Verify run_job_in_background was called with correct parameters
        assert mock_run_job.called
        call_kwargs = mock_run_job.call_args.kwargs
        assert call_kwargs["backend"] == "ollama"
        assert call_kwargs["model"] == "llava"

    @patch("lumina.jobs.background_jobs.run_job_in_background")
    def test_start_auto_tag_with_continue_pipeline(
        self, mock_run_job, client, db_session
    ):
        """Test starting auto-tag with continue_pipeline flag."""
        # Create a real catalog in the test database
        catalog_id = uuid.uuid4()
        catalog = Catalog(
            id=catalog_id,
            name="Pipeline Test Catalog",
            schema_name=f"catalog_{str(catalog_id).replace('-', '_')}",
            source_directories=["/tmp/test"],
        )
        db_session.add(catalog)
        db_session.commit()

        # Mock run_job_in_background
        mock_run_job.return_value = None

        response = client.post(
            f"/api/catalogs/{catalog.id}/auto-tag",
            params={"backend": "openclip", "continue_pipeline": True},
        )

        assert response.status_code == 200

        # Verify run_job_in_background was called with continue_pipeline=True
        assert mock_run_job.called
        call_kwargs = mock_run_job.call_args.kwargs
        assert call_kwargs["continue_pipeline"] is True

    def test_start_auto_tag_catalog_not_found(self, client, db_session):
        """Test auto-tag with non-existent catalog returns 404."""
        fake_id = uuid.uuid4()
        response = client.post(
            f"/api/catalogs/{fake_id}/auto-tag",
            params={"backend": "openclip"},
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_start_auto_tag_invalid_backend(self, client, db_session):
        """Test auto-tag with invalid backend returns 400."""
        # Create a real catalog in the test database
        catalog_id = uuid.uuid4()
        catalog = Catalog(
            id=catalog_id,
            name="Invalid Backend Test",
            schema_name=f"catalog_{str(catalog_id).replace('-', '_')}",
            source_directories=["/tmp/test"],
        )
        db_session.add(catalog)
        db_session.commit()

        response = client.post(
            f"/api/catalogs/{catalog.id}/auto-tag",
            params={"backend": "invalid_backend"},
        )

        assert response.status_code == 400
        assert "Invalid backend" in response.json()["detail"]

    @patch("lumina.jobs.background_jobs.run_job_in_background")
    def test_start_auto_tag_with_custom_threshold(
        self, mock_run_job, client, db_session
    ):
        """Test starting auto-tag with custom threshold."""
        # Create a real catalog in the test database
        catalog_id = uuid.uuid4()
        catalog = Catalog(
            id=catalog_id,
            name="Threshold Test Catalog",
            schema_name=f"catalog_{str(catalog_id).replace('-', '_')}",
            source_directories=["/tmp/test"],
        )
        db_session.add(catalog)
        db_session.commit()

        # Mock run_job_in_background
        mock_run_job.return_value = None

        response = client.post(
            f"/api/catalogs/{catalog.id}/auto-tag",
            params={"backend": "openclip", "threshold": 0.5, "max_tags": 5},
        )

        assert response.status_code == 200

        # Verify run_job_in_background was called with custom parameters
        assert mock_run_job.called
        call_kwargs = mock_run_job.call_args.kwargs
        assert call_kwargs["threshold"] == 0.5
        assert call_kwargs["max_tags"] == 5

    def test_start_auto_tag_threshold_validation(self, client, db_session):
        """Test auto-tag threshold validation (must be 0.0-1.0)."""
        # Create a real catalog in the test database
        catalog_id = uuid.uuid4()
        catalog = Catalog(
            id=catalog_id,
            name="Validation Test Catalog",
            schema_name=f"catalog_{str(catalog_id).replace('-', '_')}",
            source_directories=["/tmp/test"],
        )
        db_session.add(catalog)
        db_session.commit()

        # Threshold > 1.0 should fail
        response = client.post(
            f"/api/catalogs/{catalog.id}/auto-tag",
            params={"backend": "openclip", "threshold": 1.5},
        )

        assert response.status_code == 422  # Validation error

    def test_start_auto_tag_max_tags_validation(self, client, db_session):
        """Test auto-tag max_tags validation (must be 1-50)."""
        # Create a real catalog in the test database
        catalog_id = uuid.uuid4()
        catalog = Catalog(
            id=catalog_id,
            name="Max Tags Validation Test",
            schema_name=f"catalog_{str(catalog_id).replace('-', '_')}",
            source_directories=["/tmp/test"],
        )
        db_session.add(catalog)
        db_session.commit()

        # max_tags > 50 should fail
        response = client.post(
            f"/api/catalogs/{catalog.id}/auto-tag",
            params={"backend": "openclip", "max_tags": 100},
        )

        assert response.status_code == 422  # Validation error
