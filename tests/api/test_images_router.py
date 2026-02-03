"""Tests for images API router."""

import uuid

import pytest
from fastapi.testclient import TestClient

from lumina.db.models import Image


@pytest.fixture
def test_images(db_session, test_catalog_id: uuid.UUID) -> list[Image]:
    """Create test images for the API tests."""
    images = [
        Image(
            id=f"img-api-{uuid.uuid4().hex[:8]}",
            catalog_id=test_catalog_id,
            source_path=f"/test/path/image{i}.jpg",
            file_type="image",
            checksum=f"check{i}",
            size_bytes=1000 * (i + 1),
            status_id="active",
            quality_score=80 + i,
            dates={},
            metadata_json={},
            processing_flags={},
        )
        for i in range(3)
    ]
    for img in images:
        db_session.add(img)
    db_session.commit()
    for img in images:
        db_session.refresh(img)
    return images


def test_list_images(
    client: TestClient, test_images: list[Image], test_catalog_id: uuid.UUID
) -> None:
    """Should list images in a catalog."""
    response = client.get(f"/api/images?catalog_id={test_catalog_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3


def test_list_images_with_limit(
    client: TestClient, test_images: list[Image], test_catalog_id: uuid.UUID
) -> None:
    """Should respect limit parameter."""
    response = client.get(f"/api/images?catalog_id={test_catalog_id}&limit=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


def test_list_images_with_offset(
    client: TestClient, test_images: list[Image], test_catalog_id: uuid.UUID
) -> None:
    """Should respect offset parameter."""
    response = client.get(f"/api/images?catalog_id={test_catalog_id}&offset=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1


def test_get_image(client: TestClient, test_images: list[Image]) -> None:
    """Should get a single image by ID."""
    image = test_images[0]
    response = client.get(f"/api/images/{image.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == image.id
    assert data["source_path"] == image.source_path


def test_get_image_not_found(client: TestClient) -> None:
    """Should return 404 for non-existent image."""
    response = client.get("/api/images/nonexistent-id")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_update_image_rating(client: TestClient, test_images: list[Image]) -> None:
    """Should update image rating."""
    image = test_images[0]
    response = client.patch(f"/api/images/{image.id}?rating=4")
    assert response.status_code == 200
    assert response.json()["status"] == "updated"

    # Verify the update
    get_response = client.get(f"/api/images/{image.id}")
    assert get_response.status_code == 200
    # Rating 4 * 20 = 80
    assert get_response.json()["quality_score"] == 80


def test_update_image_not_found(client: TestClient) -> None:
    """Should return 404 when updating non-existent image."""
    response = client.patch("/api/images/nonexistent-id?rating=3")
    assert response.status_code == 404


def test_get_thumbnail_not_found(client: TestClient, test_images: list[Image]) -> None:
    """Should return 404 when thumbnail not available."""
    image = test_images[0]
    # Our test images don't have thumbnails
    response = client.get(f"/api/images/{image.id}/thumbnail")
    assert response.status_code == 404
    assert "thumbnail" in response.json()["detail"].lower()


def test_get_thumbnail_image_not_found(client: TestClient) -> None:
    """Should return 404 for non-existent image thumbnail."""
    response = client.get("/api/images/nonexistent-id/thumbnail")
    assert response.status_code == 404


def test_get_full_image_not_found(client: TestClient) -> None:
    """Should return 404 for non-existent image full."""
    response = client.get("/api/images/nonexistent-id/full")
    assert response.status_code == 404
