"""L1: Exact duplicate detection via SHA-256 checksum match."""

from collections import defaultdict
from typing import Any, Dict, Iterator, List

from ..types import CandidatePair


def detect_exact(images: List[Dict[str, Any]]) -> Iterator[CandidatePair]:
    """Yield pairs with identical checksums.

    Confidence is always 1.0 — byte-for-byte identical.

    Args:
        images: List of dicts with keys: id, checksum, source_path, created_at
    """
    by_checksum: Dict[str, List[Dict]] = defaultdict(list)
    for img in images:
        if img.get("checksum"):
            by_checksum[img["checksum"]].append(img)

    for checksum, group in by_checksum.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                # Enforce canonical ordering before building meta
                if a["id"] > b["id"]:
                    a, b = b, a
                yield CandidatePair(
                    image_id_a=a["id"],
                    image_id_b=b["id"],
                    layer="exact",
                    confidence=1.0,
                    detection_meta={
                        "checksum": checksum,
                        "path_a": a.get("source_path", ""),
                        "path_b": b.get("source_path", ""),
                    },
                )
