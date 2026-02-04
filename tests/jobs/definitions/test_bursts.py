"""Tests for bursts job definition."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from lumina.jobs.definitions.bursts import (
    bursts_job,
    detect_catalog_bursts,
    discover_images_for_bursts,
)
from lumina.jobs.framework import REGISTRY


def test_bursts_job_registered() -> None:
    """Bursts job should be in global registry."""
    assert REGISTRY.get("detect_bursts") is not None


def test_bursts_job_configuration() -> None:
    """Bursts job should have appropriate settings for single-pass."""
    assert bursts_job.batch_size == 100000  # Large batch for single pass
    assert bursts_job.max_workers == 1  # Single worker for this algorithm
    assert bursts_job.finalize is None  # Processing handles everything


def test_discover_with_provider() -> None:
    """Should use provider function when given."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)

    def provider(catalog_id: str) -> List[Dict[str, Any]]:
        return [
            {"id": "1", "timestamp": base_time, "camera": "Canon"},
            {
                "id": "2",
                "timestamp": base_time + timedelta(seconds=0.5),
                "camera": "Canon",
            },
        ]

    result = discover_images_for_bursts("catalog-123", images_provider=provider)
    assert len(result) == 2
    assert result[0]["id"] == "1"


def test_detect_catalog_bursts_finds_burst() -> None:
    """Should detect images taken in rapid succession."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)

    images = [
        {"id": "1", "timestamp": base_time, "camera": "Canon", "quality_score": 70},
        {
            "id": "2",
            "timestamp": base_time + timedelta(seconds=0.5),
            "camera": "Canon",
            "quality_score": 95,
        },
        {
            "id": "3",
            "timestamp": base_time + timedelta(seconds=1.0),
            "camera": "Canon",
            "quality_score": 80,
        },
        {
            "id": "4",
            "timestamp": base_time + timedelta(hours=1),
            "camera": "Canon",
            "quality_score": 60,
        },
    ]

    result = detect_catalog_bursts(
        images,
        "catalog-123",
        gap_threshold=2.0,
        min_size=3,
    )

    assert result["bursts_detected"] == 1
    assert result["images_in_bursts"] == 3


def test_detect_catalog_bursts_no_bursts() -> None:
    """Should handle no bursts case."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)

    images = [
        {"id": "1", "timestamp": base_time, "camera": "Canon"},
        {
            "id": "2",
            "timestamp": base_time + timedelta(minutes=5),
            "camera": "Canon",
        },
        {
            "id": "3",
            "timestamp": base_time + timedelta(minutes=10),
            "camera": "Canon",
        },
    ]

    result = detect_catalog_bursts(
        images,
        "catalog-123",
        gap_threshold=2.0,
        min_size=3,
    )

    assert result["bursts_detected"] == 0
    assert result["images_in_bursts"] == 0


def test_detect_catalog_bursts_selects_best() -> None:
    """Should select best image in each burst by quality."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)

    images = [
        {"id": "1", "timestamp": base_time, "camera": "Canon", "quality_score": 70},
        {
            "id": "2",
            "timestamp": base_time + timedelta(seconds=0.5),
            "camera": "Canon",
            "quality_score": 95,  # Best quality
        },
        {
            "id": "3",
            "timestamp": base_time + timedelta(seconds=1.0),
            "camera": "Canon",
            "quality_score": 80,
        },
    ]

    bursts_found: List[Dict[str, Any]] = []

    def save_bursts(catalog_id: str, bursts: List[Dict[str, Any]]) -> None:
        bursts_found.extend(bursts)

    result = detect_catalog_bursts(
        images,
        "catalog-123",
        gap_threshold=2.0,
        min_size=3,
        save_bursts=save_bursts,
    )

    assert result["bursts_detected"] == 1
    assert len(bursts_found) == 1
    assert bursts_found[0]["best_image_id"] == "2"  # Highest quality


def test_detect_catalog_bursts_empty() -> None:
    """Should handle empty image list."""
    result = detect_catalog_bursts([], "catalog-123")

    assert result["bursts_detected"] == 0
    assert result["images_in_bursts"] == 0
