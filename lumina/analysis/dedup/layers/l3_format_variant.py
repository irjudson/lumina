"""L3: Format variant detection — same shot, different file format.

Groups images by (capture_time_second, camera_make, camera_model).
Within each group, yields pairs where formats differ and perceptual
hashes are within threshold.

Catches: RAW+JPEG camera pairs, RAW+TIFF exports, format conversions.
"""

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from lumina.analysis.hashing import hamming_distance

from ..types import CandidatePair

# Formats considered "original" — preferred as the kept copy
RAW_FORMATS = {"raw", "arw", "cr2", "cr3", "nef", "dng", "orf", "rw2", "raf", "pef"}


def _time_bucket(capture_time: Optional[datetime]) -> Optional[str]:
    """Floor capture_time to the nearest second as a string grouping key."""
    if not capture_time:
        return None
    return capture_time.strftime("%Y%m%d%H%M%S")


def detect_format_variants(
    images: List[Dict[str, Any]],
    threshold: float = 4.0,
) -> Iterator[CandidatePair]:
    """Yield pairs that are the same shot in different file formats.

    Args:
        images: List of dicts with keys: id, format, dhash, capture_time,
                camera_make, camera_model
        threshold: Maximum Hamming distance for dhash match (default 4)
    """
    # Group by (capture_time_second, camera_make, camera_model)
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for img in images:
        bucket = _time_bucket(img.get("capture_time"))
        make = (img.get("camera_make") or "").strip()
        model = (img.get("camera_model") or "").strip()
        if bucket and (make or model):
            key = f"{bucket}|{make}|{model}"
            groups[key].append(img)

    for _key, group in groups.items():
        if len(group) < 2:
            continue

        # Only process groups with multiple distinct formats
        formats_in_group = {(img.get("format") or "").lower() for img in group}
        if len(formats_in_group) < 2:
            continue

        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                img_i, img_j = group[i], group[j]
                fmt_i = (img_i.get("format") or "").lower()
                fmt_j = (img_j.get("format") or "").lower()

                if fmt_i == fmt_j:
                    continue  # same format — L1 or L5's job

                hash_i = img_i.get("dhash") or ""
                hash_j = img_j.get("dhash") or ""
                if not hash_i or not hash_j or len(hash_i) != len(hash_j):
                    continue

                dist = hamming_distance(hash_i, hash_j)
                if dist > threshold:
                    continue

                # Determine canonical order (id_a < id_b) before building meta
                if img_i["id"] < img_j["id"]:
                    a, b = img_i, img_j
                    fmt_a, fmt_b = fmt_i, fmt_j
                else:
                    a, b = img_j, img_i
                    fmt_a, fmt_b = fmt_j, fmt_i

                # Confidence: 1.0 at distance 0, scales down by Hamming distance
                hash_bits = len(hash_i) * 4  # hex chars → bits
                confidence = 1.0 - dist / hash_bits

                yield CandidatePair(
                    image_id_a=a["id"],
                    image_id_b=b["id"],
                    layer="format_variant",
                    confidence=confidence,
                    detection_meta={
                        "hamming": dist,
                        "format_a": fmt_a,
                        "format_b": fmt_b,
                        "capture_time": str(a.get("capture_time")),
                        "camera": f"{a.get('camera_make', '')} {a.get('camera_model', '')}".strip(),
                    },
                )
