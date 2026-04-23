"""Tests for auto_resolve_duplicates_job pick_primary logic.

Tests the quality tiebreaker rules without hitting the database.
"""

import os
import re
from typing import Optional

# --- Inline helpers from auto_resolve_duplicates_job ---

FORMAT_TIER = {
    "RAW": 100,
    "TIFF": 80,
    "HEIC": 60,
    "HEIF": 60,
    "JPEG": 50,
    "JPG": 50,
    "PNG": 45,
    "GIF": 10,
}


def _filename_score(path: str) -> int:
    """Compute filename quality score (copied from auto_resolve_duplicates_job)."""
    stem = os.path.splitext(os.path.basename(path))[0]
    score = 0
    if re.search(r"20\d{2}[_\-]?\d{4}", stem):
        score += 3
    if re.search(r"\d{8}", stem):
        score += 2
    if len(stem) > 12:
        score += 1
    if re.match(r"^(IMG|DSC|DSCF|MVI|MOV|VID|P\d+|image)[-_]?\d+$", stem, re.I):
        score -= 2
    if re.match(r"^\d{4,8}$", stem):
        score -= 1
    return score


class _FakeRow:
    """Simulate a SQLAlchemy row for pick_primary tests."""

    def __init__(
        self,
        image_id_a: str = "aaa",
        image_id_b: str = "bbb",
        layer: str = "near_duplicate",
        format_a: Optional[str] = "JPEG",
        format_b: Optional[str] = "JPEG",
        width_a: int = 100,
        height_a: int = 100,
        width_b: int = 100,
        height_b: int = 100,
        size_a: int = 1000,
        size_b: int = 1000,
        path_a: str = "/photos/IMG_001.jpg",
        path_b: str = "/photos/IMG_002.jpg",
    ):
        self.image_id_a = image_id_a
        self.image_id_b = image_id_b
        self.layer = layer
        self.format_a = format_a
        self.format_b = format_b
        self.width_a = width_a
        self.height_a = height_a
        self.width_b = width_b
        self.height_b = height_b
        self.size_a = size_a
        self.size_b = size_b
        self.path_a = path_a
        self.path_b = path_b


def _pick_primary(row) -> tuple:
    """Replicate the pick_primary logic from auto_resolve_duplicates_job."""
    pid_a, pid_b = str(row.image_id_a), str(row.image_id_b)

    # For format_variant: prefer higher format tier
    if row.layer == "format_variant":
        tier_a = FORMAT_TIER.get((row.format_a or "").upper(), 40)
        tier_b = FORMAT_TIER.get((row.format_b or "").upper(), 40)
        if tier_a != tier_b:
            return (pid_a if tier_a > tier_b else pid_b, "format_tier")

    # Higher resolution wins
    pixels_a = (row.width_a or 0) * (row.height_a or 0)
    pixels_b = (row.width_b or 0) * (row.height_b or 0)
    if pixels_a != pixels_b:
        return (pid_a if pixels_a > pixels_b else pid_b, "resolution")

    # Larger file wins
    size_a, size_b = row.size_a or 0, row.size_b or 0
    size_ratio = abs(size_a - size_b) / max(size_a, size_b, 1)
    if size_ratio > 0.05:
        return (pid_a if size_a > size_b else pid_b, "file_size")

    # Better filename wins
    fn_a = _filename_score(row.path_a or "")
    fn_b = _filename_score(row.path_b or "")
    if fn_a != fn_b:
        return (pid_a if fn_a > fn_b else pid_b, "filename")

    # Tiebreak: larger file
    return (pid_a if size_a >= size_b else pid_b, "tiebreak_size")


# ======================== format_tier tests ========================


class TestFormatTier:
    """Format tier logic for format_variant layer."""

    def test_raw_beats_jpeg(self):
        row = _FakeRow(
            layer="format_variant",
            format_a="RAW",
            format_b="JPEG",
            # same resolution so resolution rule wouldn't fire
            width_a=100,
            height_a=100,
            width_b=100,
            height_b=100,
        )
        primary, reason = _pick_primary(row)
        assert primary == "aaa"
        assert reason == "format_tier"

    def test_jpeg_loses_to_tiff(self):
        row = _FakeRow(
            layer="format_variant",
            format_a="JPEG",
            format_b="TIFF",
            width_a=100,
            height_a=100,
            width_b=100,
            height_b=100,
        )
        primary, reason = _pick_primary(row)
        assert primary == "bbb"
        assert reason == "format_tier"

    def test_heic_beats_jpeg(self):
        row = _FakeRow(
            layer="format_variant",
            format_a="HEIC",
            format_b="JPEG",
            width_a=100,
            height_a=100,
            width_b=100,
            height_b=100,
        )
        primary, reason = _pick_primary(row)
        assert primary == "aaa"
        assert reason == "format_tier"

    def test_same_format_falls_through_to_resolution(self):
        row = _FakeRow(
            layer="format_variant",
            format_a="JPEG",
            format_b="JPEG",
            width_a=200,
            height_a=200,
            width_b=100,
            height_b=100,
        )
        primary, reason = _pick_primary(row)
        assert primary == "aaa"
        assert reason == "resolution"

    def test_format_tier_ignored_for_near_duplicate_layer(self):
        """format_tier rule only applies to format_variant layer."""
        row = _FakeRow(
            layer="near_duplicate",
            format_a="RAW",
            format_b="JPEG",
            width_a=100,
            height_a=100,
            width_b=200,
            height_b=200,  # B has higher resolution
        )
        primary, reason = _pick_primary(row)
        assert reason == "resolution"
        assert primary == "bbb"


# ======================== resolution tests ========================


class TestResolution:
    def test_higher_resolution_wins(self):
        row = _FakeRow(
            width_a=4000,
            height_a=3000,  # 12 MP
            width_b=2000,
            height_b=1500,  # 3 MP
        )
        primary, reason = _pick_primary(row)
        assert primary == "aaa"
        assert reason == "resolution"

    def test_b_higher_resolution_wins(self):
        row = _FakeRow(
            width_a=100,
            height_a=100,
            width_b=200,
            height_b=200,
        )
        primary, reason = _pick_primary(row)
        assert primary == "bbb"
        assert reason == "resolution"

    def test_zero_dimensions_loses(self):
        row = _FakeRow(
            width_a=0,
            height_a=0,
            width_b=100,
            height_b=100,
        )
        primary, reason = _pick_primary(row)
        assert primary == "bbb"
        assert reason == "resolution"


# ======================== file_size tests ========================


class TestFileSize:
    def test_larger_file_wins_when_significant_difference(self):
        """6% size difference is above the 5% threshold."""
        row = _FakeRow(
            width_a=100,
            height_a=100,
            width_b=100,
            height_b=100,
            size_a=1060,
            size_b=1000,
        )
        primary, reason = _pick_primary(row)
        assert primary == "aaa"
        assert reason == "file_size"

    def test_small_size_difference_falls_through(self):
        """4% size difference is below the 5% threshold → falls through to filename."""
        row = _FakeRow(
            width_a=100,
            height_a=100,
            width_b=100,
            height_b=100,
            size_a=1040,
            size_b=1000,
            path_a="/photos/IMG_001.jpg",
            path_b="/photos/20230615_120000.jpg",  # timestamp filename → higher score
        )
        _, reason = _pick_primary(row)
        # Not "file_size" — the small difference should not trigger it
        assert reason != "file_size"

    def test_zero_size_files(self):
        """Both zero size falls through to filename comparison."""
        row = _FakeRow(
            width_a=100,
            height_a=100,
            width_b=100,
            height_b=100,
            size_a=0,
            size_b=0,
            path_a="/photos/20230101_120000.jpg",  # better filename
            path_b="/photos/IMG_001.jpg",
        )
        primary, reason = _pick_primary(row)
        assert reason in ("filename", "tiebreak_size")


# ======================== filename score tests ========================


class TestFilenameScore:
    def test_timestamp_filename_scores_high(self):
        score = _filename_score("20230615_120000.jpg")
        assert score >= 3  # matches both the 8-digit pattern and year pattern

    def test_generic_img_filename_scores_negative(self):
        score = _filename_score("IMG_1234.jpg")
        assert score < 0

    def test_descriptive_name_scores_positively(self):
        score = _filename_score("family_vacation_beach_2023.jpg")
        assert score >= 1  # length > 12

    def test_pure_numeric_stem_negative(self):
        """5-digit numeric filename only triggers the pure-numeric penalty → negative."""
        score = _filename_score("12345.jpg")
        assert score < 0

    def test_timestamp_beats_generic(self):
        ts_score = _filename_score("20230615.jpg")
        generic_score = _filename_score("IMG_001.jpg")
        assert ts_score > generic_score


# ======================== tiebreak tests ========================


class TestTiebreak:
    def test_completely_identical_picks_a_on_tie(self):
        """When size_a == size_b, tiebreak goes to a (size_a >= size_b)."""
        row = _FakeRow(
            width_a=100,
            height_a=100,
            width_b=100,
            height_b=100,
            size_a=1000,
            size_b=1000,
            path_a="/photos/IMG_001.jpg",
            path_b="/photos/IMG_002.jpg",
        )
        primary, reason = _pick_primary(row)
        assert reason == "tiebreak_size"
        assert primary == "aaa"  # size_a >= size_b (equal) → a wins
