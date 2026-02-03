"""Tests for image repository."""

import uuid
from typing import Generator

import pytest
from sqlmodel import Session

from lumina.models.image import FileType, Image


def test_image_repository_inherits_base(db_session: Session) -> None:
    """ImageRepository should inherit from BaseRepository."""
    from lumina.db.repositories.image import ImageRepository

    repo = ImageRepository(db_session)
    assert hasattr(repo, "get")
    assert hasattr(repo, "list")
    assert hasattr(repo, "add")
    assert hasattr(repo, "update")
    assert hasattr(repo, "delete")


def test_get_by_catalog(
    db_session: Session,
    test_catalog_id: uuid.UUID,
    sample_image_data: list[dict],
) -> None:
    """Should get images by catalog ID."""
    from lumina.db.repositories.image import ImageRepository

    repo = ImageRepository(db_session)

    # Create test images
    for data in sample_image_data:
        repo.add(Image(**data))
    repo.commit()

    result = repo.get_by_catalog(test_catalog_id, limit=10)
    assert len(result) == 3

    # Test pagination
    result = repo.get_by_catalog(test_catalog_id, limit=2, offset=0)
    assert len(result) == 2


def test_get_by_catalog_empty(db_session: Session) -> None:
    """Should return empty list for unknown catalog."""
    from lumina.db.repositories.image import ImageRepository

    repo = ImageRepository(db_session)
    result = repo.get_by_catalog(uuid.uuid4())
    assert len(result) == 0


def test_get_without_hashes(
    db_session: Session,
    test_catalog_id: uuid.UUID,
    sample_image_data: list[dict],
) -> None:
    """Should get image IDs that need hash computation."""
    from lumina.db.repositories.image import ImageRepository

    repo = ImageRepository(db_session)

    # Create test images
    for data in sample_image_data:
        repo.add(Image(**data))
    repo.commit()

    result = repo.get_without_hashes(test_catalog_id)
    # Only the third image has no hash
    assert len(result) == 1
    # The ID includes the catalog ID suffix
    assert sample_image_data[2]["id"] in result


def test_get_with_hashes(
    db_session: Session,
    test_catalog_id: uuid.UUID,
    sample_image_data: list[dict],
) -> None:
    """Should get images with hashes for duplicate detection."""
    from lumina.db.repositories.image import ImageRepository

    repo = ImageRepository(db_session)

    # Create test images
    for data in sample_image_data:
        repo.add(Image(**data))
    repo.commit()

    result = repo.get_with_hashes(test_catalog_id)
    # First two images have hashes
    assert len(result) == 2

    # Check structure
    first = result[0]
    assert "id" in first
    assert "checksum" in first
    assert "dhash" in first
    assert "ahash" in first
    assert "whash" in first
    assert "quality_score" in first
    assert "size_bytes" in first


def test_get_with_timestamps(
    db_session: Session,
    test_catalog_id: uuid.UUID,
    sample_image_data: list[dict],
) -> None:
    """Should get images with timestamps for burst detection."""
    from lumina.db.repositories.image import ImageRepository

    repo = ImageRepository(db_session)

    # Create test images
    for data in sample_image_data:
        repo.add(Image(**data))
    repo.commit()

    result = repo.get_with_timestamps(test_catalog_id)
    assert len(result) == 3

    # Check structure
    first = result[0]
    assert "id" in first
    assert "timestamp" in first
    assert "camera" in first
    assert "quality_score" in first


def test_update_hashes(
    db_session: Session,
    test_catalog_id: uuid.UUID,
    sample_image_data: list[dict],
) -> None:
    """Should update image hashes."""
    from lumina.db.repositories.image import ImageRepository

    repo = ImageRepository(db_session)

    # Create test images
    for data in sample_image_data:
        repo.add(Image(**data))
    repo.commit()

    # Get the ID of the image without hashes (third one)
    img_id = sample_image_data[2]["id"]

    # Update hashes for image without hashes
    repo.update_hashes(
        img_id,
        dhash="new_dhash_value",
        ahash="new_ahash_value",
        whash="new_whash_value",
    )
    repo.commit()

    # Verify
    image = repo.get(img_id)
    assert image is not None
    assert image.dhash == "new_dhash_value"
    assert image.ahash == "new_ahash_value"
    assert image.whash == "new_whash_value"


def test_update_hashes_nonexistent(db_session: Session) -> None:
    """Should handle nonexistent image gracefully."""
    from lumina.db.repositories.image import ImageRepository

    repo = ImageRepository(db_session)

    # Should not raise
    repo.update_hashes(
        "nonexistent-id",
        dhash="new_dhash",
        ahash="new_ahash",
        whash="new_whash",
    )
