"""L5: Near-duplicate detection via BK-tree over dhash_8 values."""

from typing import Any, Dict, Iterator, List, Set, Tuple

from lumina.analysis.hashing import hamming_distance

from ..bktree import BKTree
from ..types import CandidatePair

HASH_BITS = 64  # dhash_8 is 64-bit


def detect_near_duplicates(
    images: List[Dict[str, Any]],
    threshold: float = 8.0,
) -> Iterator[CandidatePair]:
    """Yield near-duplicate pairs within Hamming distance threshold.

    Uses a BK-tree over dhash_8 values for O(n log n) average performance.
    Only images with a valid dhash are indexed.

    Args:
        images: List of dicts with keys: id, dhash
        threshold: Maximum Hamming distance (default 8; adaptive per catalog)
    """
    hashable = [(img["id"], img["dhash"]) for img in images if img.get("dhash")]
    if len(hashable) < 2:
        return

    tree = BKTree(hamming_distance, hashable)
    seen: Set[Tuple[str, str]] = set()
    max_dist = int(threshold)

    for img_id, img_hash in hashable:
        for neighbor_id, dist in tree.find(img_hash, max_dist):
            if neighbor_id == img_id:
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
