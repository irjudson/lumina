import numpy as np
import pytest

from lumina.jobs.definitions.cluster_faces import (
    _dbscan,
    _parse_embeddings,
    _representative_face,
)

# ─────────────────────────── _parse_embeddings ───────────────────────────


def test_parse_embeddings_string_format():
    raw = ["[0.1,0.2,0.3]", "[0.4,0.5,0.6]"]
    result = _parse_embeddings(raw)
    expected = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]], dtype=np.float32)
    np.testing.assert_allclose(result, expected, rtol=1e-6)


def test_parse_embeddings_list_input():
    raw = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    result = _parse_embeddings(raw)
    expected = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32)
    np.testing.assert_array_equal(result, expected)


def test_parse_embeddings_mixed_input():
    raw = ["[0.1,0.2,0.3]", [0.4, 0.5, 0.6]]
    result = _parse_embeddings(raw)
    assert result.shape == (2, 3)
    np.testing.assert_allclose(result[0], [0.1, 0.2, 0.3], rtol=1e-6)
    np.testing.assert_allclose(result[1], [0.4, 0.5, 0.6], rtol=1e-6)


def test_parse_embeddings_shape_and_dtype():
    raw = ["[0.1,0.2,0.3,0.4]", "[0.5,0.6,0.7,0.8]", "[0.9,1.0,1.1,1.2]"]
    result = _parse_embeddings(raw)
    assert result.shape == (3, 4)
    assert result.dtype == np.float32


def test_parse_embeddings_single_embedding():
    raw = ["[1.0,2.0,3.0]"]
    result = _parse_embeddings(raw)
    assert result.shape == (1, 3)
    assert result.dtype == np.float32
    np.testing.assert_allclose(result[0], [1.0, 2.0, 3.0], rtol=1e-6)


# ─────────────────────────── _representative_face ───────────────────────────


def test_representative_face_single():
    embeddings = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
    labels = np.array([0])
    assert _representative_face(embeddings, labels, 0) == 0


def test_representative_face_closer_to_centroid_wins():
    # Three-face cluster; b sits between a and c so it is closest to the centroid.
    a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    b_raw = np.array([0.99, 0.141, 0.0], dtype=np.float32)
    b = b_raw / np.linalg.norm(b_raw)
    c = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    embeddings = np.stack([a, b, c])
    labels = np.array([0, 0, 0])
    rep = _representative_face(embeddings, labels, 0)
    assert rep == 1  # b is closest to the centroid


def test_representative_face_noncontiguous_indices():
    # cluster label 1 lives at positions 1 and 3 in the full labels array
    embeddings = np.array(
        [
            [0.0, 1.0, 0.0],  # label 0
            [1.0, 0.01, 0.0],  # label 1 – very close to centroid of cluster 1
            [0.0, 0.0, 1.0],  # label 0
            [0.9, 0.436, 0.0],  # label 1 – further from centroid
        ],
        dtype=np.float32,
    )
    labels = np.array([0, 1, 0, 1])
    rep = _representative_face(embeddings, labels, 1)
    # global index of representative must be 1 (closest to centroid of cluster 1)
    assert rep == 1


# ─────────────────────────── _dbscan ───────────────────────────


def test_dbscan_nearly_identical_same_cluster():
    a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    b = a + np.float32(1e-4)
    embeddings = np.stack([a / np.linalg.norm(a), b / np.linalg.norm(b)])
    labels = _dbscan(embeddings, eps=0.4, min_samples=2)
    assert labels[0] == labels[1]
    assert labels[0] != -1


def test_dbscan_orthogonal_embeddings_not_same_cluster():
    embeddings = np.array(
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        dtype=np.float32,
    )
    labels = _dbscan(embeddings, eps=0.4, min_samples=2)
    # orthogonal vectors have cosine distance = 1.0 >> eps; both should be noise
    assert labels[0] == -1
    assert labels[1] == -1


def test_dbscan_all_same_single_cluster():
    v = np.array([0.6, 0.8, 0.0], dtype=np.float32)
    embeddings = np.tile(v, (5, 1))
    labels = _dbscan(embeddings, eps=0.4, min_samples=2)
    assert set(labels) == {0}


def test_dbscan_noise_label():
    # Three very different unit vectors; with min_samples=3 none form a cluster
    embeddings = np.array(
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float32,
    )
    labels = _dbscan(embeddings, eps=0.4, min_samples=3)
    assert all(lbl == -1 for lbl in labels)
