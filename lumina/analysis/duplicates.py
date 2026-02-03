"""Pure functions for duplicate detection.

These functions identify duplicate and similar images based on
checksums and perceptual hashes. They handle grouping logic
without database access or progress tracking.
"""

from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple

from .hashing import hamming_distance


def group_by_exact_match(
    images: List[Dict[str, Any]],
    checksum_key: str = "checksum",
) -> List[Dict[str, Any]]:
    """Group images by exact checksum match.

    Args:
        images: List of image dicts with checksum field
        checksum_key: Key for checksum in image dict

    Returns:
        List of group dicts with image_ids and similarity_type
    """
    by_checksum: Dict[str, List[str]] = defaultdict(list)

    for img in images:
        checksum = img.get(checksum_key)
        if checksum:
            by_checksum[checksum].append(img["id"])

    groups = []
    for _checksum, ids in by_checksum.items():
        if len(ids) > 1:
            groups.append(
                {
                    "image_ids": ids,
                    "similarity_type": "exact",
                    "confidence": 100,
                }
            )

    return groups


def find_similar_hashes(
    hashes: Dict[str, str],
    threshold: int = 5,
) -> List[Set[str]]:
    """Find groups of similar hashes using union-find.

    Args:
        hashes: Dict mapping image_id -> hash string
        threshold: Maximum Hamming distance to consider similar

    Returns:
        List of sets, each containing similar image IDs
    """
    # Union-find for efficient grouping
    parent: Dict[str, str] = {id: id for id in hashes}

    def find(x: str) -> str:
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x: str, y: str) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    # Compare all pairs
    ids = list(hashes.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            id1, id2 = ids[i], ids[j]
            distance = hamming_distance(hashes[id1], hashes[id2])
            if distance <= threshold:
                union(id1, id2)

    # Collect groups
    groups: Dict[str, Set[str]] = defaultdict(set)
    for id in ids:
        root = find(id)
        groups[root].add(id)

    # Return only groups with multiple members
    return [g for g in groups.values() if len(g) > 1]


def group_by_similarity(
    images: List[Dict[str, Any]],
    hash_key: str = "dhash",
    threshold: int = 5,
) -> List[Dict[str, Any]]:
    """Group images by perceptual hash similarity.

    Args:
        images: List of image dicts with hash field
        hash_key: Key for hash in image dict (dhash, ahash, whash)
        threshold: Maximum Hamming distance

    Returns:
        List of group dicts with image_ids, similarity_type, confidence
    """
    # Build hash lookup
    hashes = {}
    for img in images:
        hash_val = img.get(hash_key)
        if hash_val:
            hashes[img["id"]] = hash_val

    if not hashes:
        return []

    # Find similar groups
    similar_sets = find_similar_hashes(hashes, threshold)

    # Convert to output format
    groups = []
    for id_set in similar_sets:
        # Calculate average similarity within group
        ids = list(id_set)
        total_dist = 0
        comparisons = 0
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                total_dist += hamming_distance(hashes[ids[i]], hashes[ids[j]])
                comparisons += 1

        avg_dist = total_dist / comparisons if comparisons else 0
        # Convert distance to confidence (lower distance = higher confidence)
        # threshold of 5 on 64-bit hash means max distance is ~8% of bits
        confidence = int(100 * (1 - avg_dist / 64))

        groups.append(
            {
                "image_ids": ids,
                "similarity_type": "perceptual",
                "confidence": max(0, min(100, confidence)),
            }
        )

    return groups


def select_primary_image(
    images: List[Dict[str, Any]],
    quality_key: str = "quality_score",
) -> str:
    """Select the best image from a group as primary.

    Selection criteria (in order):
    1. Highest quality score
    2. Largest file size
    3. First by ID (deterministic)

    Args:
        images: List of image dicts
        quality_key: Key for quality score

    Returns:
        ID of the primary image
    """
    if not images:
        raise ValueError("Cannot select from empty list")

    def sort_key(img: Dict[str, Any]) -> Tuple[int, int, str]:
        return (
            img.get(quality_key) or 0,
            img.get("size_bytes") or 0,
            img.get("id", ""),
        )

    best = max(images, key=sort_key)
    return best["id"]
