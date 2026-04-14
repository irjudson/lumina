"""Shared types for the deduplication pipeline."""

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class CandidatePair:
    """A potential duplicate pair produced by a detection layer.

    image_id_a is always lexicographically smaller than image_id_b.
    This canonical ordering ensures (a,b) and (b,a) are treated as the same pair.
    """

    image_id_a: str
    image_id_b: str
    layer: str
    confidence: float
    detection_meta: Dict[str, Any]
    verify_carefully: bool = False
    verify_reason: str = ""

    def __post_init__(self) -> None:
        # Enforce canonical ordering: id_a < id_b always
        if self.image_id_a > self.image_id_b:
            self.image_id_a, self.image_id_b = self.image_id_b, self.image_id_a
