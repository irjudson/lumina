"""L2: Re-import detection via source_path match."""

from collections import defaultdict
from typing import Any, Dict, Iterator, List

from ..types import CandidatePair


def detect_reimport(images: List[Dict[str, Any]]) -> Iterator[CandidatePair]:
    """Yield pairs sharing the same source_path (same file scanned twice).

    Confidence is always 1.0 — same physical file path.
    detection_meta includes created_at timestamps to show when each import happened.

    Args:
        images: List of dicts with keys: id, checksum, source_path, created_at
    """
    by_path: Dict[str, List[Dict]] = defaultdict(list)
    for img in images:
        if img.get("source_path"):
            by_path[img["source_path"]].append(img)

    for path, group in by_path.items():
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
                    layer="reimport",
                    confidence=1.0,
                    detection_meta={
                        "source_path": path,
                        "created_at_a": str(a.get("created_at", "")),
                        "created_at_b": str(b.get("created_at", "")),
                    },
                )
