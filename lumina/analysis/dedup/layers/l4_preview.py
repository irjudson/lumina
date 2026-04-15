# lumina/analysis/dedup/layers/l4_preview.py
"""L4: Preview/derivative detection via scale-invariant perceptual hash."""

import re
from datetime import timedelta
from math import sqrt
from typing import Any, Dict, Iterator, List

from lumina.analysis.hashing import hamming_distance

from ..types import CandidatePair

SMALL_IMAGE_PIXELS = 1_000_000  # 1MP safety threshold

PREVIEW_PATH_PATTERNS = [
    "/Previews/",
    "/.lrdata/",
    "/cache/",
    "/Cache/",
    "/Thumbs/",
    "/Lightroom/",
    "/.thumbnails/",
    "/proxies/",
    "/Proxies/",
]
PREVIEW_EXTENSIONS = {".lrprev"}
PREVIEW_NAME_RE = re.compile(r"_(preview|thumb|sm|proxy|low|web)\b", re.I)
RAW_FORMATS = {"raw", "arw", "cr2", "cr3", "nef", "dng", "orf", "rw2", "raf", "pef"}


def _count_corroborating_signals(small: Dict, large: Dict) -> int:
    path = small.get("source_path") or ""
    signals = 0

    if any(p in path for p in PREVIEW_PATH_PATTERNS):
        signals += 1
    if any(path.endswith(ext) for ext in PREVIEW_EXTENSIONS):
        signals += 1
    if PREVIEW_NAME_RE.search(path):
        signals += 1

    # EXIF stripped or capture_time mismatch
    if small.get("metadata_json", {}).get("exif_stripped"):
        signals += 1
    if small.get("capture_time") and large.get("capture_time"):
        if small["capture_time"] != large["capture_time"]:
            signals += 1

    # File created significantly after capture (likely an export)
    if small.get("created_at") and large.get("capture_time"):
        try:
            if small["created_at"] > large["capture_time"] + timedelta(minutes=5):
                signals += 1
        except TypeError:
            pass

    # Large is RAW, small is JPEG
    large_fmt = (large.get("format") or "").lower()
    small_fmt = (small.get("format") or "").lower()
    if large_fmt in RAW_FORMATS and small_fmt == "jpeg":
        signals += 1

    return signals


def _size_band_candidates(
    large: Dict,
    all_images: List[Dict],
    min_ratio: float = 0.05,
    max_ratio: float = 0.95,
) -> Iterator[Dict]:
    """Yield images smaller than large within the size ratio band."""
    large_pixels = (large.get("width") or 0) * (large.get("height") or 0)
    if large_pixels == 0:
        return
    for img in all_images:
        if img["id"] == large["id"]:
            continue
        small_pixels = (img.get("width") or 0) * (img.get("height") or 0)
        if small_pixels == 0:
            continue
        ratio = small_pixels / large_pixels
        if min_ratio <= ratio <= max_ratio:
            yield img


def detect_previews(
    images: List[Dict[str, Any]],
    threshold: float = 3.0,
) -> Iterator[CandidatePair]:
    """Yield pairs where a smaller image is likely a preview of a larger one.

    Uses scale-aware hash comparison:
    - scale > 0.5  → compare dhash_16 (256-bit)
    - scale > 0.25 → compare dhash_8  (64-bit)
    - scale ≤ 0.25 → skip (too small to hash reliably)

    Small images (<1MP) require ≥2 corroborating signals and are
    hard-capped at 0.65 confidence with verify_carefully=True.
    """
    # Sort largest-first so we compare small against their likely originals
    by_size = sorted(
        images,
        key=lambda i: (i.get("width") or 0) * (i.get("height") or 0),
        reverse=True,
    )

    for large in by_size:
        large_pixels = (large.get("width") or 0) * (large.get("height") or 0)
        if large_pixels < SMALL_IMAGE_PIXELS:
            break  # remaining images are all small — no more large originals

        for small in _size_band_candidates(large, images):
            small_pixels = (small.get("width") or 0) * (small.get("height") or 0)
            scale = sqrt(small_pixels / large_pixels)

            # Choose hash resolution by scale
            if scale > 0.5:
                hash_large = large.get("dhash_16") or ""
                hash_small = small.get("dhash_16") or ""
                hash_bits = 256
            elif scale > 0.25:
                hash_large = large.get("dhash") or ""
                hash_small = small.get("dhash") or ""
                hash_bits = 64
            else:
                continue  # too small

            if not hash_large or not hash_small or len(hash_large) != len(hash_small):
                continue

            dist = hamming_distance(hash_large, hash_small)
            if dist > threshold:
                continue

            corroboration = _count_corroborating_signals(small, large)
            base_confidence = 1.0 - dist / hash_bits

            if small_pixels < SMALL_IMAGE_PIXELS:
                if corroboration < 2:
                    continue
                confidence = min(base_confidence, 0.65)
                verify_carefully = True
                verify_reason = (
                    f"Small image ({small_pixels/1e6:.2f}MP) with "
                    f"{corroboration} corroborating signal(s)"
                )
            else:
                confidence = base_confidence
                verify_carefully = False
                verify_reason = ""

            yield CandidatePair(
                image_id_a=large["id"],
                image_id_b=small["id"],
                layer="preview",
                confidence=confidence,
                verify_carefully=verify_carefully,
                verify_reason=verify_reason,
                detection_meta={
                    "scale": round(scale, 3),
                    "hamming": dist,
                    "hash_bits": hash_bits,
                    "corroboration": corroboration,
                    "small_pixels": small_pixels,
                },
            )
