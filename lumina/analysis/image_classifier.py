"""
Image content classification — fast heuristics + optional Ollama VLM.

Two-tier approach:
  Tier 1 (fast, always runs):
    - PIL validation: can we open it at all? → 'invalid' if not
    - Tiny images (<= 64px either dimension) → 'invalid' (tracking pixels, icons)
    - Exact device-screen dimensions → 'screenshot'
    - Very high aspect ratio (>3:1 or <1:3) → 'screenshot'
    - Animated GIF → 'other'

  Tier 2 (optional, Ollama VLM):
    - Runs only on images that tier 1 labelled 'unknown'
    - Uses qwen3-vl or llava

Categories:
    invalid     — file can't be opened, or is too small to be a real photo
    screenshot  — device screen capture (detected by dimensions/aspect)
    photo       — real-world photograph
    document    — scanned/photographed document, receipt, form
    social_media — social media image with overlaid UI/text
    artwork     — digital art, illustration, graphic design
    other       — animated GIF, icon, or anything unclassifiable
    unknown     — not yet classified by heuristics (needs VLM or stays unknown)
"""

import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

CONTENT_CLASSES = [
    "photo",
    "screenshot",
    "document",
    "social_media",
    "artwork",
    "invalid",
    "other",
]

# Common exact device screen resolutions (w, h) — portrait and landscape
SCREEN_RESOLUTIONS = {
    # iPhones
    (1170, 2532),
    (2532, 1170),
    (1284, 2778),
    (2778, 1284),
    (1179, 2556),
    (2556, 1179),
    (1125, 2436),
    (2436, 1125),
    (750, 1334),
    (1334, 750),
    (1080, 1920),
    (1920, 1080),
    (1080, 2340),
    (2340, 1080),
    (1080, 2400),
    (2400, 1080),
    (1440, 3120),
    (3120, 1440),
    # iPad
    (2048, 2732),
    (2732, 2048),
    (1668, 2388),
    (2388, 1668),
    # Common desktop
    (1920, 1080),
    (2560, 1440),
    (3840, 2160),
    (1366, 768),
    (1280, 800),
    (1280, 1024),
    (2560, 1600),
    (1680, 1050),
    # Mac Retina
    (2560, 1664),
    (2880, 1800),
    (3456, 2234),
    # Android common
    (1080, 2160),
    (2160, 1080),
    (1440, 2960),
    (2960, 1440),
}


def heuristic_classify(image_path: Path) -> Tuple[str, str]:
    """
    Fast heuristic classification. No VLM needed.

    Returns:
        (label, reason) where label is a CONTENT_CLASSES value or 'unknown'
        'unknown' means heuristics couldn't decide — caller should use VLM.
    """
    from PIL import Image, UnidentifiedImageError

    # --- Tier 1a: can PIL open it? ---
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            fmt = img.format or ""
            n_frames = getattr(img, "n_frames", 1)
    except (UnidentifiedImageError, Exception) as e:
        return ("invalid", f"PIL cannot open: {e}")

    # --- Tier 1b: too small to be a real photo ---
    if width <= 64 or height <= 64:
        return ("invalid", f"too small ({width}x{height})")

    # --- Tier 1c: animated GIF ---
    if fmt == "GIF" and n_frames > 1:
        return ("other", "animated GIF")

    # --- Tier 1d: exact screen resolution ---
    if (width, height) in SCREEN_RESOLUTIONS:
        return ("screenshot", f"exact screen resolution {width}x{height}")

    # --- Tier 1e: extreme aspect ratio (>3.5:1) → screenshot/banner ---
    ratio = max(width, height) / max(min(width, height), 1)
    if ratio > 3.5:
        return ("screenshot", f"extreme aspect ratio {ratio:.1f}:1")

    return ("unknown", "no heuristic matched")


class ImageClassifier:
    """Classifies images by content type.

    Runs fast PIL heuristics first; uses Ollama VLM only for images
    that heuristics can't resolve.
    """

    MAX_DIMENSION = 512

    def __init__(self, model: str = "qwen3-vl", host: Optional[str] = None) -> None:
        self.model = model
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self._client = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import ollama

                self._client = ollama.Client(host=self.host)
            except ImportError as e:
                raise ImportError("Install with: pip install ollama") from e
        return self._client

    def _prepare_image(self, image_path: Path) -> Optional[bytes]:
        try:
            from PIL import Image

            img = Image.open(image_path).convert("RGB")
            img.thumbnail((self.MAX_DIMENSION, self.MAX_DIMENSION), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=80)
            return buf.getvalue()
        except Exception as e:
            logger.warning(f"Could not prepare image {image_path}: {e}")
            return None

    def classify_with_vlm(self, image_path: Path) -> str:
        """Run Ollama VLM classification. Returns a CONTENT_CLASSES string."""
        prompt = (
            "Classify this image into exactly one category:\n"
            "- photo: real-world photograph of people, places, nature, events, objects\n"
            "- screenshot: screen capture from a phone, computer, app, or website\n"
            "- document: scanned/photographed document, receipt, form, page of text\n"
            "- social_media: image designed for social media with overlaid UI/text/watermarks\n"
            "- artwork: digital art, illustration, drawing, painting, graphic design\n"
            "- other: anything else\n\n"
            "Reply with ONLY the single category word."
        )
        image_bytes = self._prepare_image(image_path)
        if image_bytes is None:
            return "other"
        try:
            client = self._get_client()
            response = client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt, "images": [image_bytes]}],
            )
            raw = response["message"]["content"].strip().lower()
            word = raw.split()[0].rstrip(".,;:!?") if raw else "other"
            word = word.replace("-", "_")
            if word in CONTENT_CLASSES:
                return word
            for cls in CONTENT_CLASSES:
                if cls in raw:
                    return cls
            return "other"
        except Exception as e:
            logger.warning(f"VLM classification failed for {image_path}: {e}")
            return "other"

    def classify(self, image_path: Path, use_vlm: bool = False) -> str:
        """Classify a single image using heuristics, optionally falling back to VLM."""
        label, reason = heuristic_classify(image_path)
        if label != "unknown":
            return label
        if use_vlm:
            return self.classify_with_vlm(image_path)
        return "unknown"
