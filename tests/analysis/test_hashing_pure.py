"""Tests for pure hashing functions."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lumina.analysis.hashing import (
    compute_ahash,
    compute_all_hashes,
    compute_dhash,
    compute_whash,
    hamming_distance,
    similarity_score,
)


def test_hamming_distance_identical():
    """Identical hashes should have distance 0."""
    h1 = "0000000000000000"
    h2 = "0000000000000000"
    assert hamming_distance(h1, h2) == 0


def test_hamming_distance_one_bit():
    """One bit difference should give distance 1."""
    h1 = "0000000000000000"
    h2 = "0000000000000001"
    assert hamming_distance(h1, h2) == 1


def test_hamming_distance_max():
    """Maximum difference for 64-bit hash."""
    h1 = "0000000000000000"
    h2 = "ffffffffffffffff"
    assert hamming_distance(h1, h2) == 64


def test_hamming_distance_mismatch_length():
    """Should raise on length mismatch."""
    with pytest.raises(ValueError):
        hamming_distance("00", "0000")


def test_similarity_score_identical():
    """Identical hashes should have 100% similarity."""
    assert similarity_score("abcd1234abcd1234", "abcd1234abcd1234") == 100


def test_similarity_score_different():
    """Completely different hashes should have 0% similarity."""
    assert similarity_score("0000000000000000", "ffffffffffffffff") == 0


@pytest.fixture
def sample_image(tmp_path):
    """Create a sample image for testing."""
    img_path = tmp_path / "test.png"
    # Create a simple 64x64 gradient image
    arr = np.zeros((64, 64, 3), dtype=np.uint8)
    for i in range(64):
        for j in range(64):
            arr[i, j] = [i * 4, j * 4, (i + j) * 2]
    img = Image.fromarray(arr)
    img.save(img_path)
    return img_path


def test_compute_dhash(sample_image):
    """Should compute dhash."""
    result = compute_dhash(sample_image)
    assert isinstance(result, str)
    assert len(result) == 16  # 64-bit hash as hex


def test_compute_ahash(sample_image):
    """Should compute ahash."""
    result = compute_ahash(sample_image)
    assert isinstance(result, str)
    assert len(result) == 16


def test_compute_whash(sample_image):
    """Should compute whash."""
    result = compute_whash(sample_image)
    assert isinstance(result, str)
    assert len(result) == 16


def test_compute_all_hashes(sample_image):
    """Should compute all three hash types."""
    hashes = compute_all_hashes(sample_image)
    assert "dhash" in hashes
    assert "ahash" in hashes
    assert "whash" in hashes
    assert all(len(h) == 16 for h in hashes.values())
