"""Core modules for catalog management.

Pure analysis functions are available in lumina.analysis:
- lumina.analysis.hashing: compute_dhash, compute_ahash, compute_whash, etc.
- lumina.analysis.bursts: detect_bursts, select_best_in_burst
- lumina.analysis.duplicates: find_similar_hashes, group_by_similarity, etc.
"""

from typing import Any


def __getattr__(name: str) -> Any:
    """Lazy imports to avoid circular dependencies."""
    if name in (
        "compute_dhash",
        "compute_ahash",
        "compute_whash",
        "compute_all_hashes",
        "hamming_distance",
        "similarity_score",
    ):
        from lumina.analysis import hashing

        return getattr(hashing, name)
    elif name in ("detect_bursts", "select_best_in_burst"):
        from lumina.analysis import bursts

        return getattr(bursts, name)
    elif name in (
        "find_similar_hashes",
        "group_by_exact_match",
        "group_by_similarity",
        "select_primary_image",
    ):
        from lumina.analysis import duplicates

        return getattr(duplicates, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
