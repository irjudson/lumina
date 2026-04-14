"""Pipeline orchestrator: runs layers, checks suppression, upserts candidates."""

import json
import logging
from typing import Iterator, Set, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from .types import CandidatePair

logger = logging.getLogger(__name__)


def load_suppression_set(catalog_id: str, session: Session) -> Set[Tuple[str, str]]:
    """Load all suppressed pairs for a catalog as a set of (id_a, id_b) tuples.

    Joins through images to scope suppression to the catalog.
    """
    rows = session.execute(
        text(
            """
            SELECT DISTINCT sp.id_a, sp.id_b
            FROM suppression_pairs sp
            WHERE EXISTS (
                SELECT 1 FROM images i
                WHERE i.id = sp.id_a AND i.catalog_id = :cid::uuid
            )
        """
        ),
        {"cid": catalog_id},
    ).fetchall()
    return {(row.id_a, row.id_b) for row in rows}


def filter_suppressed(
    candidates: Iterator[CandidatePair],
    suppressed: Set[Tuple[str, str]],
) -> Iterator[CandidatePair]:
    """Filter out pairs that have already been reviewed."""
    for c in candidates:
        pair = (min(c.image_id_a, c.image_id_b), max(c.image_id_a, c.image_id_b))
        if pair not in suppressed:
            yield c


def upsert_candidate(candidate: CandidatePair, session: Session) -> None:
    """Insert or refresh a candidate pair. Idempotent on (image_id_a, image_id_b, layer).

    On conflict, updates confidence, verify flags, and detection_meta.
    Does NOT touch reviewed_at — already-reviewed candidates are preserved.
    """
    session.execute(
        text(
            """
            INSERT INTO duplicate_candidates
                (id, catalog_id, image_id_a, image_id_b, layer, confidence,
                 verify_carefully, verify_reason, detection_meta, created_at)
            SELECT
                gen_random_uuid(),
                i.catalog_id,
                :a, :b, :layer, :confidence,
                :verify_carefully, :verify_reason, :meta::jsonb, NOW()
            FROM images i WHERE i.id = :a
            ON CONFLICT (image_id_a, image_id_b, layer)
            DO UPDATE SET
                confidence = EXCLUDED.confidence,
                verify_carefully = EXCLUDED.verify_carefully,
                verify_reason = EXCLUDED.verify_reason,
                detection_meta = EXCLUDED.detection_meta
            WHERE duplicate_candidates.reviewed_at IS NULL
        """
        ),
        {
            "a": candidate.image_id_a,
            "b": candidate.image_id_b,
            "layer": candidate.layer,
            "confidence": candidate.confidence,
            "verify_carefully": candidate.verify_carefully,
            "verify_reason": candidate.verify_reason or "",
            "meta": json.dumps(candidate.detection_meta),
        },
    )
