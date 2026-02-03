"""Tests for pure duplicate detection functions."""

from lumina.analysis.duplicates import (
    find_similar_hashes,
    group_by_exact_match,
    group_by_similarity,
    select_primary_image,
)


def test_group_by_exact_match():
    """Should group images with identical checksums."""
    images = [
        {"id": "1", "checksum": "abc"},
        {"id": "2", "checksum": "def"},
        {"id": "3", "checksum": "abc"},
        {"id": "4", "checksum": "def"},
        {"id": "5", "checksum": "ghi"},
    ]

    groups = group_by_exact_match(images)

    assert len(groups) == 2  # Two groups with duplicates
    group_ids = [sorted(g["image_ids"]) for g in groups]
    assert ["1", "3"] in group_ids
    assert ["2", "4"] in group_ids


def test_group_by_exact_match_no_duplicates():
    """Should return empty when no duplicates."""
    images = [
        {"id": "1", "checksum": "abc"},
        {"id": "2", "checksum": "def"},
        {"id": "3", "checksum": "ghi"},
    ]

    groups = group_by_exact_match(images)
    assert len(groups) == 0


def test_find_similar_hashes():
    """Should find hashes within threshold."""
    hashes = {
        "img1": "0000000000000000",
        "img2": "0000000000000001",  # 1 bit diff
        "img3": "ffffffffffffffff",  # Very different
        "img4": "0000000000000003",  # 2 bits diff from img1
    }

    similar = find_similar_hashes(hashes, threshold=5)

    # img1, img2, img4 should be grouped (within threshold)
    # img3 should be separate
    assert len(similar) >= 1
    # Find the group containing img1
    img1_group = next((g for g in similar if "img1" in g), None)
    assert img1_group is not None
    assert "img2" in img1_group
    assert "img4" in img1_group
    assert "img3" not in img1_group


def test_find_similar_hashes_no_similar():
    """Should return empty when no similar hashes."""
    hashes = {
        "img1": "0000000000000000",
        "img2": "ffffffffffffffff",
    }

    similar = find_similar_hashes(hashes, threshold=5)
    assert len(similar) == 0


def test_group_by_similarity():
    """Should group images by perceptual hash similarity."""
    images = [
        {"id": "1", "dhash": "0000000000000000"},
        {"id": "2", "dhash": "0000000000000001"},  # 1 bit diff
        {"id": "3", "dhash": "ffffffffffffffff"},  # Very different
    ]

    groups = group_by_similarity(images, hash_key="dhash", threshold=5)

    assert len(groups) == 1
    assert set(groups[0]["image_ids"]) == {"1", "2"}
    assert groups[0]["similarity_type"] == "perceptual"
    assert groups[0]["confidence"] > 90  # High confidence for 1-bit difference


def test_group_by_similarity_no_hash():
    """Should skip images without hash."""
    images = [
        {"id": "1", "dhash": "0000000000000000"},
        {"id": "2"},  # No hash
        {"id": "3", "dhash": "0000000000000001"},
    ]

    groups = group_by_similarity(images, hash_key="dhash", threshold=5)

    assert len(groups) == 1
    assert set(groups[0]["image_ids"]) == {"1", "3"}


def test_select_primary_image_by_quality():
    """Should select highest quality image."""
    images = [
        {"id": "1", "quality_score": 80, "size_bytes": 1000},
        {"id": "2", "quality_score": 95, "size_bytes": 500},
        {"id": "3", "quality_score": 70, "size_bytes": 2000},
    ]

    primary = select_primary_image(images)
    assert primary == "2"  # Highest quality


def test_select_primary_image_by_size():
    """Should fall back to size when quality equal."""
    images = [
        {"id": "1", "quality_score": 80, "size_bytes": 1000},
        {"id": "2", "quality_score": 80, "size_bytes": 2000},
        {"id": "3", "quality_score": 80, "size_bytes": 500},
    ]

    primary = select_primary_image(images)
    assert primary == "2"  # Largest size


def test_select_primary_image_empty():
    """Should raise on empty list."""
    import pytest

    with pytest.raises(ValueError):
        select_primary_image([])
