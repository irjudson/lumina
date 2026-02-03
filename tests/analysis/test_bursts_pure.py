"""Tests for pure burst detection functions."""

from datetime import datetime, timedelta

from lumina.analysis.bursts import detect_bursts, select_best_in_burst


def test_detect_bursts_basic():
    """Should detect images taken in rapid succession."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)

    images = [
        {"id": "1", "timestamp": base_time, "camera": "Canon"},
        {
            "id": "2",
            "timestamp": base_time + timedelta(seconds=0.5),
            "camera": "Canon",
        },
        {
            "id": "3",
            "timestamp": base_time + timedelta(seconds=1.0),
            "camera": "Canon",
        },
        {"id": "4", "timestamp": base_time + timedelta(hours=1), "camera": "Canon"},
    ]

    bursts = detect_bursts(images, gap_threshold=2.0, min_size=3)

    assert len(bursts) == 1
    assert set(bursts[0]["image_ids"]) == {"1", "2", "3"}


def test_detect_bursts_different_cameras():
    """Should not group images from different cameras."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)

    # Images from different cameras at same times - should not be grouped
    images = [
        {"id": "1", "timestamp": base_time, "camera": "Canon"},
        {
            "id": "2",
            "timestamp": base_time + timedelta(seconds=0.5),
            "camera": "Nikon",
        },
        {
            "id": "3",
            "timestamp": base_time + timedelta(seconds=5.0),
            "camera": "Canon",
        },
    ]

    bursts = detect_bursts(images, gap_threshold=2.0, min_size=2)

    # Should not form a burst - cameras are different and same-camera images
    # have too large a gap (5 seconds > 2.0 threshold)
    assert len(bursts) == 0


def test_detect_bursts_too_few_images():
    """Should not detect burst with fewer than min_size images."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)

    images = [
        {"id": "1", "timestamp": base_time, "camera": "Canon"},
        {
            "id": "2",
            "timestamp": base_time + timedelta(seconds=0.5),
            "camera": "Canon",
        },
    ]

    bursts = detect_bursts(images, gap_threshold=2.0, min_size=3)
    assert len(bursts) == 0


def test_detect_bursts_gap_too_large():
    """Should not group images with gaps exceeding threshold."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)

    images = [
        {"id": "1", "timestamp": base_time, "camera": "Canon"},
        {"id": "2", "timestamp": base_time + timedelta(seconds=5), "camera": "Canon"},
        {"id": "3", "timestamp": base_time + timedelta(seconds=10), "camera": "Canon"},
    ]

    bursts = detect_bursts(images, gap_threshold=2.0, min_size=3)
    assert len(bursts) == 0


def test_detect_bursts_duration_info():
    """Should include duration info in burst."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)

    images = [
        {"id": "1", "timestamp": base_time, "camera": "Canon"},
        {
            "id": "2",
            "timestamp": base_time + timedelta(seconds=1.0),
            "camera": "Canon",
        },
        {
            "id": "3",
            "timestamp": base_time + timedelta(seconds=2.0),
            "camera": "Canon",
        },
    ]

    bursts = detect_bursts(images, gap_threshold=2.0, min_size=3)

    assert len(bursts) == 1
    assert bursts[0]["start_time"] == base_time
    assert bursts[0]["duration_seconds"] == 2.0
    assert bursts[0]["camera"] == "Canon"


def test_select_best_in_burst_quality():
    """Should select highest quality image."""
    images = [
        {"id": "1", "quality_score": 70},
        {"id": "2", "quality_score": 95},
        {"id": "3", "quality_score": 85},
    ]

    best = select_best_in_burst(images)
    assert best == "2"


def test_select_best_in_burst_first():
    """Should select first image when method is 'first'."""
    images = [
        {"id": "1", "quality_score": 70},
        {"id": "2", "quality_score": 95},
    ]

    best = select_best_in_burst(images, method="first")
    assert best == "1"


def test_select_best_in_burst_middle():
    """Should select middle image when method is 'middle'."""
    images = [
        {"id": "1", "quality_score": 70},
        {"id": "2", "quality_score": 95},
        {"id": "3", "quality_score": 85},
    ]

    best = select_best_in_burst(images, method="middle")
    assert best == "2"


def test_select_best_in_burst_empty():
    """Should raise on empty list."""
    import pytest

    with pytest.raises(ValueError):
        select_best_in_burst([])
