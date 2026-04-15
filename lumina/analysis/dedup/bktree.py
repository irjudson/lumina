"""Pure Python BK-tree for efficient nearest-neighbor search in metric spaces.

A BK-tree supports queries of the form "find all items within distance d
of query q". Triangle inequality pruning eliminates large subtrees early,
giving far better average performance than O(n²) brute force for
sparse metric spaces like Hamming distance over perceptual hashes.
"""

from typing import Any, Callable, Iterable, List, Tuple


class BKTree:
    """BK-tree for metric space nearest-neighbor search.

    Args:
        distance_fn: A function (a, b) -> int that satisfies the metric axioms.
        items: Iterable of (id, value) tuples to index.
    """

    def __init__(
        self,
        distance_fn: Callable[[Any, Any], int],
        items: Iterable[Tuple[Any, Any]],
    ) -> None:
        self._dist = distance_fn
        self._root: Any = None  # [id, value, children: dict[int, node]]

        for item_id, value in items:
            self._insert(item_id, value)

    def _insert(self, item_id: Any, value: Any) -> None:
        if self._root is None:
            self._root = [item_id, value, {}]
            return
        node = self._root
        while True:
            d = self._dist(value, node[1])
            if d in node[2]:
                node = node[2][d]
            else:
                node[2][d] = [item_id, value, {}]
                break

    def find(self, query: Any, max_distance: int) -> List[Tuple[Any, int]]:
        """Return all (id, distance) pairs within max_distance of query."""
        if self._root is None:
            return []
        results: List[Tuple[Any, int]] = []
        stack = [self._root]
        while stack:
            node = stack.pop()
            d = self._dist(query, node[1])
            if d <= max_distance:
                results.append((node[0], d))
            lo = max(0, d - max_distance)
            hi = d + max_distance
            for dist_key, child in node[2].items():
                if lo <= dist_key <= hi:
                    stack.append(child)
        return results
