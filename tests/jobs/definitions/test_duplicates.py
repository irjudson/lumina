"""Tests for duplicates job definition."""

from pathlib import Path
from typing import Any, Dict, List

from lumina.jobs.definitions.duplicates import (
    compute_image_hashes,
    discover_images_for_hashing,
    duplicates_job,
    finalize_duplicates,
)
from lumina.jobs.framework import REGISTRY


def test_duplicates_job_registered() -> None:
    """Duplicates job should be in global registry."""
    assert REGISTRY.get("detect_duplicates") is not None


def test_duplicates_job_configuration() -> None:
    """Duplicates job should have appropriate settings."""
    assert duplicates_job.batch_size == 1000
    assert duplicates_job.finalize is not None
    assert duplicates_job.max_workers == 4


def test_discover_with_provider() -> None:
    """Should use provider function when given."""

    def provider(catalog_id: str) -> List[str]:
        return ["img-1", "img-2", "img-3"]

    result = discover_images_for_hashing("catalog-123", images_provider=provider)
    assert result == ["img-1", "img-2", "img-3"]


def test_compute_image_hashes_success(tmp_path: Path) -> None:
    """Should compute all hash types for an image."""
    import numpy as np
    from PIL import Image

    # Create a test image
    img_path = tmp_path / "test.png"
    arr = np.zeros((64, 64, 3), dtype=np.uint8)
    for i in range(64):
        for j in range(64):
            arr[i, j] = [i * 4, j * 4, (i + j) * 2]
    img = Image.fromarray(arr)
    img.save(img_path)

    def path_provider(catalog_id: str, image_id: str) -> str:
        return str(img_path)

    result = compute_image_hashes(
        "img-1",
        "catalog-123",
        path_provider=path_provider,
    )

    assert result["image_id"] == "img-1"
    assert result["success"] is True
    assert "hashes" in result
    assert "dhash" in result["hashes"]
    assert "ahash" in result["hashes"]
    assert "whash" in result["hashes"]


def test_compute_image_hashes_failure() -> None:
    """Should handle errors gracefully."""

    def path_provider(catalog_id: str, image_id: str) -> str:
        return "/nonexistent/path.jpg"

    result = compute_image_hashes(
        "img-1",
        "catalog-123",
        path_provider=path_provider,
    )

    assert result["image_id"] == "img-1"
    assert result["success"] is False
    assert "error" in result


def test_finalize_duplicates_exact() -> None:
    """Should detect exact duplicates by checksum."""
    # Mock images with same checksums
    images = [
        {"id": "1", "checksum": "abc123", "dhash": "0000000000000000"},
        {"id": "2", "checksum": "abc123", "dhash": "0000000000000001"},
        {"id": "3", "checksum": "def456", "dhash": "ffffffffffffffff"},
    ]

    def images_provider(catalog_id: str) -> List[Dict[str, Any]]:
        return images

    results: List[Dict[str, Any]] = []  # Empty - finalize doesn't use results

    summary = finalize_duplicates(
        results,
        "catalog-123",
        images_provider=images_provider,
    )

    assert summary["exact_groups"] == 1  # One group of 2 exact duplicates


def test_finalize_duplicates_perceptual() -> None:
    """Should detect perceptually similar images."""
    # Images with similar hashes (low hamming distance)
    images = [
        {"id": "1", "checksum": "a", "dhash": "0000000000000000"},
        {"id": "2", "checksum": "b", "dhash": "0000000000000001"},  # 1 bit diff
        {"id": "3", "checksum": "c", "dhash": "0000000000000003"},  # 2 bits diff
        {"id": "4", "checksum": "d", "dhash": "ffffffffffffffff"},  # Very different
    ]

    def images_provider(catalog_id: str) -> List[Dict[str, Any]]:
        return images

    results: List[Dict[str, Any]] = []

    summary = finalize_duplicates(
        results,
        "catalog-123",
        images_provider=images_provider,
    )

    # 1, 2, 3 should be perceptually similar (within threshold of 5)
    assert summary["perceptual_groups"] >= 1


def test_finalize_duplicates_empty() -> None:
    """Should handle empty image list."""

    def images_provider(catalog_id: str) -> List[Dict[str, Any]]:
        return []

    results: List[Dict[str, Any]] = []

    summary = finalize_duplicates(
        results,
        "catalog-123",
        images_provider=images_provider,
    )

    assert summary["exact_groups"] == 0
    assert summary["perceptual_groups"] == 0
    assert summary["total_duplicates"] == 0
