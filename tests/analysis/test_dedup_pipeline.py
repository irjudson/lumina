"""Tests for the deduplication detection pipeline."""


def test_candidate_pair_canonical_ordering():
    """image_id_a is always the lex-smaller of the two."""
    from lumina.analysis.dedup.types import CandidatePair

    p = CandidatePair(
        image_id_a="zzz",
        image_id_b="aaa",
        layer="exact",
        confidence=1.0,
        detection_meta={},
    )
    assert p.image_id_a == "aaa"
    assert p.image_id_b == "zzz"


def test_candidate_pair_already_ordered():
    """Already-ordered pairs are unchanged."""
    from lumina.analysis.dedup.types import CandidatePair

    p = CandidatePair(
        image_id_a="aaa",
        image_id_b="zzz",
        layer="exact",
        confidence=1.0,
        detection_meta={},
    )
    assert p.image_id_a == "aaa"
    assert p.image_id_b == "zzz"


def test_l1_exact_finds_checksum_duplicates():
    from lumina.analysis.dedup.layers.l1_exact import detect_exact

    images = [
        {
            "id": "img-1",
            "checksum": "abc123",
            "source_path": "/a/1.jpg",
            "created_at": None,
        },
        {
            "id": "img-2",
            "checksum": "abc123",
            "source_path": "/a/2.jpg",
            "created_at": None,
        },
        {
            "id": "img-3",
            "checksum": "zzz999",
            "source_path": "/a/3.jpg",
            "created_at": None,
        },
    ]
    pairs = list(detect_exact(images))
    assert len(pairs) == 1
    assert pairs[0].layer == "exact"
    assert pairs[0].confidence == 1.0
    assert {pairs[0].image_id_a, pairs[0].image_id_b} == {"img-1", "img-2"}
    meta = pairs[0].detection_meta
    assert "checksum" in meta
    assert "path_a" in meta
    assert "path_b" in meta
    # path_a should correspond to image_id_a (the lex-smaller ID)
    assert meta["path_a"] != meta["path_b"]


def test_l1_exact_no_duplicates():
    from lumina.analysis.dedup.layers.l1_exact import detect_exact

    images = [
        {
            "id": "img-1",
            "checksum": "aaa",
            "source_path": "/a/1.jpg",
            "created_at": None,
        },
        {
            "id": "img-2",
            "checksum": "bbb",
            "source_path": "/a/2.jpg",
            "created_at": None,
        },
    ]
    assert list(detect_exact(images)) == []


def test_l1_exact_three_way_duplicate():
    """Three images with same checksum should produce 3 pairs."""
    from lumina.analysis.dedup.layers.l1_exact import detect_exact

    images = [
        {"id": "a", "checksum": "same", "source_path": "/1.jpg", "created_at": None},
        {"id": "b", "checksum": "same", "source_path": "/2.jpg", "created_at": None},
        {"id": "c", "checksum": "same", "source_path": "/3.jpg", "created_at": None},
    ]
    pairs = list(detect_exact(images))
    assert len(pairs) == 3


def test_l2_reimport_finds_same_source_path():
    from lumina.analysis.dedup.layers.l2_reimport import detect_reimport

    images = [
        {
            "id": "img-1",
            "checksum": "aaa",
            "source_path": "/photos/x.jpg",
            "created_at": "2024-01-01",
        },
        {
            "id": "img-2",
            "checksum": "bbb",
            "source_path": "/photos/x.jpg",
            "created_at": "2024-06-01",
        },
        {
            "id": "img-3",
            "checksum": "ccc",
            "source_path": "/photos/y.jpg",
            "created_at": "2024-01-01",
        },
    ]
    pairs = list(detect_reimport(images))
    assert len(pairs) == 1
    assert pairs[0].layer == "reimport"
    assert {pairs[0].image_id_a, pairs[0].image_id_b} == {"img-1", "img-2"}


def test_l2_reimport_detection_meta_has_timestamps():
    from lumina.analysis.dedup.layers.l2_reimport import detect_reimport

    images = [
        {
            "id": "img-1",
            "checksum": "a",
            "source_path": "/photos/x.jpg",
            "created_at": "2024-01-01",
        },
        {
            "id": "img-2",
            "checksum": "b",
            "source_path": "/photos/x.jpg",
            "created_at": "2024-06-01",
        },
    ]
    pairs = list(detect_reimport(images))
    assert len(pairs) == 1
    meta = pairs[0].detection_meta
    assert "created_at_a" in meta and "created_at_b" in meta


def test_pipeline_filter_suppressed():
    from lumina.analysis.dedup.pipeline import filter_suppressed
    from lumina.analysis.dedup.types import CandidatePair

    candidates = [
        CandidatePair(
            image_id_a="aaa",
            image_id_b="bbb",
            layer="exact",
            confidence=1.0,
            detection_meta={},
        ),
        CandidatePair(
            image_id_a="ccc",
            image_id_b="ddd",
            layer="exact",
            confidence=1.0,
            detection_meta={},
        ),
    ]
    suppressed = {("aaa", "bbb")}
    result = list(filter_suppressed(iter(candidates), suppressed))
    assert len(result) == 1
    assert result[0].image_id_a == "ccc"


def test_l1_exact_detection_meta_labels_match_canonical_ids():
    """path_a in detection_meta must correspond to image_id_a (lex-smaller)."""
    from lumina.analysis.dedup.layers.l1_exact import detect_exact

    images = [
        {
            "id": "zzz",
            "checksum": "same",
            "source_path": "/zzz.jpg",
            "created_at": None,
        },
        {
            "id": "aaa",
            "checksum": "same",
            "source_path": "/aaa.jpg",
            "created_at": None,
        },
    ]
    pairs = list(detect_exact(images))
    assert len(pairs) == 1
    p = pairs[0]
    assert p.image_id_a == "aaa"  # lex-smaller
    assert p.image_id_b == "zzz"
    # path_a must correspond to image_id_a
    assert p.detection_meta["path_a"] == "/aaa.jpg"
    assert p.detection_meta["path_b"] == "/zzz.jpg"
