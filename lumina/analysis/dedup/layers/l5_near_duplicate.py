"""L5: Near-duplicate detection via BK-tree over dhash_16 values."""

from typing import Any, Dict, Iterator, List, Set, Tuple

from lumina.analysis.hashing import hamming_distance

from ..bktree import BKTree
from ..types import CandidatePair

HASH_BITS = 256  # dhash_16 is 256-bit (64 hex chars)


def detect_near_duplicates(
    images: List[Dict[str, Any]],
    threshold: float = 8.0,
) -> Iterator[CandidatePair]:
    """Yield near-duplicate pairs within Hamming distance threshold.

    Uses a BK-tree over dhash_16 values for O(n log n) average performance.
    dhash_16 (256-bit) provides much better discrimination than dhash_8 (64-bit),
    preventing burst-photography false positives where many sequential shots share
    the same 64-bit hash despite being distinct images.

    Only images with a valid dhash_16 (and non-zero) are indexed.

    Args:
        images: List of dicts with keys: id, dhash_16
        threshold: Maximum Hamming distance (default 8 bits out of 256; adaptive per catalog)
    """
    ZERO_HASH = "0" * 64  # degenerate all-zeros hash — skip these
    # Build index: image_id -> burst_id (None if not in a burst)
    burst_ids: Dict[str, Any] = {img["id"]: img.get("burst_id") for img in images}

    hashable = [
        (img["id"], img["dhash_16"])
        for img in images
        if img.get("dhash_16") and img["dhash_16"] != ZERO_HASH
    ]
    if len(hashable) < 2:
        return

    tree = BKTree(hamming_distance, hashable)
    seen: Set[Tuple[str, str]] = set()
    max_dist = int(threshold)

    for img_id, img_hash in hashable:
        img_burst = burst_ids.get(img_id)
        for neighbor_id, dist in tree.find(img_hash, max_dist):
            if neighbor_id == img_id:
                continue
            # Skip pairs where both images belong to the same burst —
            # similar shots within a burst are expected, not duplicates.
            if img_burst and img_burst == burst_ids.get(neighbor_id):
                continue
            pair_key = (min(img_id, neighbor_id), max(img_id, neighbor_id))
            if pair_key in seen:
                continue
            seen.add(pair_key)
            yield CandidatePair(
                image_id_a=pair_key[0],
                image_id_b=pair_key[1],
                layer="near_duplicate",
                confidence=1.0 - dist / HASH_BITS,
                detection_meta={"hamming": dist},
            )
