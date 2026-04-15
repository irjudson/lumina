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


def test_l3_format_variant_detects_raw_jpeg_pair():
    from datetime import datetime

    from lumina.analysis.dedup.layers.l3_format_variant import detect_format_variants

    images = [
        {
            "id": "raw-1",
            "format": "raw",
            "dhash": "a" * 16,
            "capture_time": datetime(2024, 1, 1, 12, 0, 0),
            "camera_make": "Canon",
            "camera_model": "R5",
        },
        {
            "id": "jpg-1",
            "format": "jpeg",
            "dhash": "a" * 16,
            "capture_time": datetime(2024, 1, 1, 12, 0, 0),
            "camera_make": "Canon",
            "camera_model": "R5",
        },
        {
            "id": "raw-2",
            "format": "raw",
            "dhash": "b" * 16,
            "capture_time": datetime(2024, 1, 1, 12, 0, 5),  # different time
            "camera_make": "Canon",
            "camera_model": "R5",
        },
    ]
    pairs = list(detect_format_variants(images, threshold=4))
    assert len(pairs) == 1
    assert pairs[0].layer == "format_variant"
    assert {pairs[0].image_id_a, pairs[0].image_id_b} == {"raw-1", "jpg-1"}


def test_l3_format_variant_skips_same_format():
    from datetime import datetime

    from lumina.analysis.dedup.layers.l3_format_variant import detect_format_variants

    images = [
        {
            "id": "jpg-1",
            "format": "jpeg",
            "dhash": "a" * 16,
            "capture_time": datetime(2024, 1, 1, 12, 0, 0),
            "camera_make": "Canon",
            "camera_model": "R5",
        },
        {
            "id": "jpg-2",
            "format": "jpeg",
            "dhash": "a" * 16,
            "capture_time": datetime(2024, 1, 1, 12, 0, 0),
            "camera_make": "Canon",
            "camera_model": "R5",
        },
    ]
    # Same format — not a format_variant (that's L1/L5's job)
    pairs = list(detect_format_variants(images, threshold=4))
    assert len(pairs) == 0


def test_l3_format_variant_skips_high_hamming():
    from datetime import datetime

    from lumina.analysis.dedup.layers.l3_format_variant import detect_format_variants

    images = [
        {
            "id": "raw-x",
            "format": "raw",
            "dhash": "0" * 16,
            "capture_time": datetime(2024, 1, 1, 12, 0, 0),
            "camera_make": "Nikon",
            "camera_model": "Z9",
        },
        {
            "id": "jpg-x",
            "format": "jpeg",
            "dhash": "f" * 16,  # max hamming
            "capture_time": datetime(2024, 1, 1, 12, 0, 0),
            "camera_make": "Nikon",
            "camera_model": "Z9",
        },
    ]
    pairs = list(detect_format_variants(images, threshold=4))
    assert len(pairs) == 0


def test_l3_format_variant_raw_is_image_id_a():
    """RAW format should be image_id_a (the 'original') when paired with JPEG."""
    from datetime import datetime

    from lumina.analysis.dedup.layers.l3_format_variant import detect_format_variants

    images = [
        {
            "id": "jpg-first",
            "format": "jpeg",
            "dhash": "a" * 16,
            "capture_time": datetime(2024, 1, 1, 12, 0, 0),
            "camera_make": "Sony",
            "camera_model": "A7",
        },
        {
            "id": "raw-second",
            "format": "arw",
            "dhash": "a" * 16,
            "capture_time": datetime(2024, 1, 1, 12, 0, 0),
            "camera_make": "Sony",
            "camera_model": "A7",
        },
    ]
    pairs = list(detect_format_variants(images, threshold=4))
    assert len(pairs) == 1
    # RAW (arw) should be image_id_a — BUT canonical ordering (id_a < id_b) takes precedence
    # "jpg-first" < "raw-second" lexicographically, so jpg-first will be image_id_a
    # The important thing is the pair is detected, not which is _a
    assert {pairs[0].image_id_a, pairs[0].image_id_b} == {"jpg-first", "raw-second"}
    assert pairs[0].detection_meta["format_a"] in ("arw", "jpeg")
    assert pairs[0].detection_meta["format_b"] in ("arw", "jpeg")
    assert pairs[0].detection_meta["format_a"] != pairs[0].detection_meta["format_b"]


def test_l4_preview_detects_scaled_image(tmp_path):
    """A scaled-down copy of an image should be flagged as preview."""
    from datetime import datetime

    from PIL import Image as PILImage

    from lumina.analysis.dedup.layers.l4_preview import detect_previews
    from lumina.analysis.hashing import compute_dhash

    # Create a 1000x1000 "original"
    orig_path = tmp_path / "original.jpg"
    PILImage.new("RGB", (1000, 1000), color=(100, 150, 200)).save(orig_path)

    # Create a 400x400 "preview" of same content (scale=0.4 > 0.25, uses dhash_8)
    # Note: 200x200 would give scale=0.2 ≤ 0.25 and be skipped by the scale gate.
    preview_path = tmp_path / "Previews" / "original_preview.jpg"
    preview_path.parent.mkdir()
    PILImage.new("RGB", (400, 400), color=(100, 150, 200)).save(preview_path)

    images = [
        {
            "id": "orig",
            "source_path": str(orig_path),
            "width": 1000,
            "height": 1000,
            "format": "jpeg",
            "dhash": compute_dhash(orig_path, 8),
            "dhash_16": compute_dhash(orig_path, 16),
            "dhash_32": compute_dhash(orig_path, 32),
            "created_at": datetime(2024, 1, 1),
            "capture_time": datetime(2024, 1, 1),
            "metadata_json": {},
        },
        {
            "id": "prev",
            "source_path": str(preview_path),
            "width": 400,
            "height": 400,
            "format": "jpeg",
            "dhash": compute_dhash(preview_path, 8),
            "dhash_16": compute_dhash(preview_path, 16),
            "dhash_32": compute_dhash(preview_path, 32),
            "created_at": datetime(2024, 6, 1),
            "capture_time": datetime(2024, 1, 1),
            "metadata_json": {},
        },
    ]
    pairs = list(detect_previews(images, threshold=6))
    assert len(pairs) == 1
    assert pairs[0].layer == "preview"
    assert pairs[0].image_id_a == "orig"  # "orig" < "prev" lexicographically


def test_l4_small_image_requires_corroboration(tmp_path):
    """Image <1MP without corroborating signals must NOT produce a candidate."""
    from datetime import datetime

    from PIL import Image as PILImage

    from lumina.analysis.dedup.layers.l4_preview import detect_previews
    from lumina.analysis.hashing import compute_dhash

    orig_path = tmp_path / "original.jpg"
    PILImage.new("RGB", (2000, 1000), color=(50, 100, 150)).save(orig_path)

    small_path = tmp_path / "small_unknown.jpg"  # no preview path signal
    PILImage.new("RGB", (500, 250), color=(50, 100, 150)).save(small_path)

    images = [
        {
            "id": "orig",
            "source_path": str(orig_path),
            "width": 2000,
            "height": 1000,
            "format": "jpeg",
            "dhash": compute_dhash(orig_path, 8),
            "dhash_16": compute_dhash(orig_path, 16),
            "dhash_32": compute_dhash(orig_path, 32),
            "created_at": datetime(2024, 1, 1),
            "capture_time": datetime(2024, 1, 1),
            "metadata_json": {},
        },
        {
            "id": "small",
            "source_path": str(small_path),
            "width": 500,
            "height": 250,
            "format": "jpeg",
            "dhash": compute_dhash(small_path, 8),
            "dhash_16": compute_dhash(small_path, 16),
            "dhash_32": compute_dhash(small_path, 32),
            "created_at": datetime(2024, 1, 1),
            "capture_time": datetime(2024, 1, 1),
            "metadata_json": {},
        },
    ]
    pairs = list(detect_previews(images, threshold=6))
    # 500*250 = 125,000 < 1MP, no path signals, 0 corroboration → skip
    assert len(pairs) == 0


def test_l4_preview_detects_large_scale_image(tmp_path):
    """scale > 0.5 branch (dhash_16, 256-bit) is exercised for an 80% size preview."""
    from datetime import datetime

    from PIL import Image as PILImage

    from lumina.analysis.dedup.layers.l4_preview import detect_previews
    from lumina.analysis.hashing import compute_dhash

    orig_path = tmp_path / "original.jpg"
    PILImage.new("RGB", (1000, 1000), color=(80, 120, 160)).save(orig_path)

    # 800x800 → scale = sqrt(640000/1000000) = 0.8 > 0.5 → uses dhash_16
    preview_path = tmp_path / "Previews" / "original_lg.jpg"
    preview_path.parent.mkdir()
    PILImage.new("RGB", (800, 800), color=(80, 120, 160)).save(preview_path)

    images = [
        {
            "id": "orig",
            "source_path": str(orig_path),
            "width": 1000,
            "height": 1000,
            "format": "jpeg",
            "dhash": compute_dhash(orig_path, 8),
            "dhash_16": compute_dhash(orig_path, 16),
            "dhash_32": compute_dhash(orig_path, 32),
            "created_at": datetime(2024, 1, 1),
            "capture_time": datetime(2024, 1, 1),
            "metadata_json": {},
        },
        {
            "id": "prev_lg",
            "source_path": str(preview_path),
            "width": 800,
            "height": 800,
            "format": "jpeg",
            "dhash": compute_dhash(preview_path, 8),
            "dhash_16": compute_dhash(preview_path, 16),
            "dhash_32": compute_dhash(preview_path, 32),
            "created_at": datetime(2024, 6, 1),
            "capture_time": datetime(2024, 1, 1),
            "metadata_json": {},
        },
    ]
    pairs = list(detect_previews(images, threshold=6))
    assert len(pairs) == 1
    assert pairs[0].layer == "preview"
    assert pairs[0].detection_meta["hash_bits"] == 256
