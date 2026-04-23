"""Tests for image content classification heuristics.

Tests heuristic_classify() — fast PIL-based classification that doesn't
need Ollama. Also tests the ImageClassifier.classify() method when use_vlm=False.
"""

from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def make_image(tmp_path):
    """Factory: create a test image at the given size and return its path."""

    def _make(
        width: int, height: int, fmt: str = "JPEG", animated: bool = False
    ) -> Path:
        name = f"{width}x{height}.{fmt.lower()}"
        path = tmp_path / name
        if animated and fmt == "GIF":
            frames = [
                Image.new("RGB", (width, height), color=(i * 30, 0, 0))
                for i in range(3)
            ]
            frames[0].save(
                path,
                format="GIF",
                save_all=True,
                append_images=frames[1:],
                loop=0,
            )
        else:
            img = Image.new("RGB", (width, height), color="white")
            img.save(path, format=fmt)
        return path

    return _make


@pytest.fixture
def invalid_file(tmp_path) -> Path:
    """Create a file that is not a valid image."""
    p = tmp_path / "not_an_image.jpg"
    p.write_bytes(b"definitely not an image")
    return p


# ======================== heuristic_classify tests ========================


class TestHeuristicClassify:
    """Tests for the heuristic_classify() function."""

    def test_invalid_file_returns_invalid(self, invalid_file):
        from lumina.analysis.image_classifier import heuristic_classify

        label, reason = heuristic_classify(invalid_file)
        assert label == "invalid"
        assert "PIL" in reason or "cannot" in reason.lower()

    def test_tiny_image_returns_invalid(self, make_image):
        from lumina.analysis.image_classifier import heuristic_classify

        path = make_image(32, 32)
        label, reason = heuristic_classify(path)
        assert label == "invalid"
        assert "small" in reason.lower()

    def test_image_at_exactly_64px_returns_invalid(self, make_image):
        from lumina.analysis.image_classifier import heuristic_classify

        path = make_image(64, 64)
        label, reason = heuristic_classify(path)
        assert label == "invalid"

    def test_normal_photo_returns_unknown(self, make_image):
        """A regular 100×100 JPEG with no distinctive features → unknown."""
        from lumina.analysis.image_classifier import heuristic_classify

        path = make_image(100, 100)
        label, _ = heuristic_classify(path)
        assert label == "unknown"

    def test_exact_screen_resolution_is_screenshot(self, make_image):
        """iPhone resolution 1170×2532 → screenshot."""
        from lumina.analysis.image_classifier import heuristic_classify

        path = make_image(1170, 2532)
        label, reason = heuristic_classify(path)
        assert label == "screenshot"
        assert "1170" in reason

    def test_landscape_screen_resolution_is_screenshot(self, make_image):
        """Full HD 1920×1080 → screenshot."""
        from lumina.analysis.image_classifier import heuristic_classify

        path = make_image(1920, 1080)
        label, reason = heuristic_classify(path)
        assert label == "screenshot"

    def test_extreme_aspect_ratio_wide_is_screenshot(self, make_image):
        """Width 4× height (4:1) exceeds 3.5:1 threshold → screenshot."""
        from lumina.analysis.image_classifier import heuristic_classify

        path = make_image(1000, 200)  # 5:1 ratio
        label, reason = heuristic_classify(path)
        assert label == "screenshot"
        assert "aspect" in reason.lower()

    def test_extreme_aspect_ratio_tall_is_screenshot(self, make_image):
        """Height 4× width (1:4) exceeds threshold → screenshot."""
        from lumina.analysis.image_classifier import heuristic_classify

        path = make_image(200, 1000)  # 1:5 ratio
        label, reason = heuristic_classify(path)
        assert label == "screenshot"

    def test_aspect_ratio_just_below_threshold_is_unknown(self, make_image):
        """3:1 ratio is below 3.5 threshold → should NOT be screenshot."""
        from lumina.analysis.image_classifier import heuristic_classify

        path = make_image(300, 100)  # 3:1 ratio
        label, _ = heuristic_classify(path)
        assert label != "screenshot"

    def test_animated_gif_returns_other(self, make_image):
        """Multi-frame GIF → other."""
        from lumina.analysis.image_classifier import heuristic_classify

        path = make_image(200, 200, fmt="GIF", animated=True)
        label, reason = heuristic_classify(path)
        assert label == "other"
        assert "animated" in reason.lower() or "GIF" in reason

    def test_static_gif_is_unknown(self, make_image):
        """Single-frame GIF is not animated → unknown (no other heuristic fires)."""
        from lumina.analysis.image_classifier import heuristic_classify

        path = make_image(200, 200, fmt="GIF", animated=False)
        label, _ = heuristic_classify(path)
        # A 200×200 static GIF should fall through to 'unknown'
        assert label == "unknown"

    def test_nonexistent_file_returns_invalid(self, tmp_path):
        from lumina.analysis.image_classifier import heuristic_classify

        label, reason = heuristic_classify(tmp_path / "nonexistent.jpg")
        assert label == "invalid"


# ======================== ImageClassifier.classify tests ==================


class TestImageClassifier:
    """Tests for ImageClassifier.classify() — heuristics only (use_vlm=False)."""

    def test_classify_returns_label_string(self, make_image):
        from lumina.analysis.image_classifier import ImageClassifier

        clf = ImageClassifier()
        path = make_image(1920, 1080)  # known screen resolution
        label = clf.classify(path, use_vlm=False)
        assert label == "screenshot"

    def test_classify_tiny_is_invalid(self, make_image):
        from lumina.analysis.image_classifier import ImageClassifier

        clf = ImageClassifier()
        path = make_image(32, 32)
        assert clf.classify(path, use_vlm=False) == "invalid"

    def test_classify_unknown_without_vlm_stays_unknown(self, make_image):
        """When use_vlm=False, 'unknown' heuristic result is returned as-is."""
        from lumina.analysis.image_classifier import ImageClassifier

        clf = ImageClassifier()
        path = make_image(300, 300)  # normal-ish size, no heuristic fires
        label = clf.classify(path, use_vlm=False)
        assert label == "unknown"

    def test_classify_invalid_returns_invalid(self, invalid_file):
        from lumina.analysis.image_classifier import ImageClassifier

        clf = ImageClassifier()
        assert clf.classify(invalid_file, use_vlm=False) == "invalid"
