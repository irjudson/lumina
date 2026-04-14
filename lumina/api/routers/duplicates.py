"""Duplicate detection review queue, decision, and archive endpoints."""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...db import get_db
from .catalogs import get_catalog

logger = logging.getLogger(__name__)
router = APIRouter()


class DecideRequest(BaseModel):
    decision: str  # confirmed_duplicate | not_duplicate | deferred
    primary_id: Optional[str] = None
    notes: Optional[str] = None


@router.get("/{catalog_id}/duplicates/candidates")
def list_candidates(
    catalog_id: uuid.UUID,
    layer: Optional[str] = None,
    min_confidence: float = 0.0,
    verify_carefully: Optional[bool] = None,
    reviewed: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """List duplicate candidates for review."""
    get_catalog(catalog_id, db)

    filters = ["dc.catalog_id = CAST(:cid AS uuid)"]
    params: Dict[str, Any] = {
        "cid": str(catalog_id),
        "limit": limit,
        "offset": offset,
    }

    if layer:
        filters.append("dc.layer = :layer")
        params["layer"] = layer
    if min_confidence > 0:
        filters.append("dc.confidence >= :min_conf")
        params["min_conf"] = min_confidence
    if verify_carefully is not None:
        filters.append("dc.verify_carefully = :vc")
        params["vc"] = verify_carefully
    if not reviewed:
        filters.append("dc.reviewed_at IS NULL")
    else:
        filters.append("dc.reviewed_at IS NOT NULL")

    where = " AND ".join(filters)

    rows = db.execute(
        text(
            f"""
            SELECT
                dc.id, dc.catalog_id, dc.image_id_a, dc.image_id_b,
                dc.layer, dc.confidence, dc.verify_carefully, dc.verify_reason,
                dc.detection_meta, dc.created_at, dc.reviewed_at,
                ia.source_path AS path_a, ia.width AS width_a, ia.height AS height_a,
                ia.format AS format_a, ia.size_bytes AS size_a,
                ib.source_path AS path_b, ib.width AS width_b, ib.height AS height_b,
                ib.format AS format_b, ib.size_bytes AS size_b
            FROM duplicate_candidates dc
            JOIN images ia ON ia.id = dc.image_id_a
            JOIN images ib ON ib.id = dc.image_id_b
            WHERE {where}
            ORDER BY dc.verify_carefully DESC, dc.confidence DESC
            LIMIT :limit OFFSET :offset
        """
        ),
        params,
    ).fetchall()

    total = db.execute(
        text(f"SELECT COUNT(*) FROM duplicate_candidates dc WHERE {where}"),
        params,
    ).scalar()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "candidates": [dict(row._mapping) for row in rows],
    }


@router.get("/{catalog_id}/duplicates/candidates/{candidate_id}")
def get_candidate(
    catalog_id: uuid.UUID,
    candidate_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get a single duplicate candidate by ID."""
    get_catalog(catalog_id, db)
    row = db.execute(
        text(
            """
            SELECT * FROM duplicate_candidates
            WHERE id = CAST(:id AS uuid) AND catalog_id = CAST(:cid AS uuid)
        """
        ),
        {"id": str(candidate_id), "cid": str(catalog_id)},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return dict(row._mapping)


@router.post("/{catalog_id}/duplicates/candidates/{candidate_id}/decide")
def decide_candidate(
    catalog_id: uuid.UUID,
    candidate_id: uuid.UUID,
    body: DecideRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Record a user decision on a duplicate candidate.

    Atomically:
    1. Writes duplicate_decisions row
    2. Marks candidate as reviewed
    3. Writes suppression_pairs entry
    4. Archives the non-primary image if confirmed_duplicate
    5. Updates detection threshold via EMA
    """
    VALID_DECISIONS = {"confirmed_duplicate", "not_duplicate", "deferred"}
    if body.decision not in VALID_DECISIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid decision. Must be one of: {VALID_DECISIONS}",
        )
    if body.decision == "confirmed_duplicate" and not body.primary_id:
        raise HTTPException(
            status_code=422,
            detail="primary_id is required for confirmed_duplicate",
        )

    get_catalog(catalog_id, db)

    candidate = db.execute(
        text(
            """
            SELECT * FROM duplicate_candidates
            WHERE id = CAST(:id AS uuid) AND catalog_id = CAST(:cid AS uuid)
        """
        ),
        {"id": str(candidate_id), "cid": str(catalog_id)},
    ).fetchone()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # 1. Write decision
    decision_id = str(uuid.uuid4())
    db.execute(
        text(
            """
            INSERT INTO duplicate_decisions (id, candidate_id, decision, primary_id, notes, decided_at)
            VALUES (CAST(:id AS uuid), CAST(:cid AS uuid), :decision, :primary_id, :notes, NOW())
        """
        ),
        {
            "id": decision_id,
            "cid": str(candidate_id),
            "decision": body.decision,
            "primary_id": body.primary_id,
            "notes": body.notes,
        },
    )

    # 2. Mark candidate reviewed
    db.execute(
        text(
            "UPDATE duplicate_candidates SET reviewed_at = NOW() WHERE id = CAST(:id AS uuid)"
        ),
        {"id": str(candidate_id)},
    )

    # 3. Suppress pair (canonical order enforced by DB constraint id_a < id_b)
    id_a = min(str(candidate.image_id_a), str(candidate.image_id_b))
    id_b = max(str(candidate.image_id_a), str(candidate.image_id_b))
    db.execute(
        text(
            """
            INSERT INTO suppression_pairs (id_a, id_b, decision, created_at)
            VALUES (:a, :b, :decision, NOW())
            ON CONFLICT (id_a, id_b) DO NOTHING
        """
        ),
        {"a": id_a, "b": id_b, "decision": body.decision},
    )

    # 4. Archive if confirmed
    if body.decision == "confirmed_duplicate":
        archive_id = (
            candidate.image_id_b
            if str(candidate.image_id_b) != body.primary_id
            else candidate.image_id_a
        )
        from ...analysis.dedup.archive import archive_image

        archive_image(
            image_id=str(archive_id),
            decision_id=decision_id,
            archive_reason=candidate.layer,
            primary_image_id=body.primary_id,
            session=db,
        )

    # 5. Update threshold (EMA adaptation)
    if body.decision != "deferred":
        _update_threshold(
            str(catalog_id),
            candidate.layer,
            candidate.detection_meta,
            body.decision,
            db,
        )

    db.commit()
    return {"decision_id": decision_id, "status": "recorded"}


def _update_threshold(
    catalog_id: str,
    layer: str,
    detection_meta: Any,
    decision: str,
    db: Session,
) -> None:
    """EMA threshold adaptation from user decision."""
    ALPHA = 0.15
    LAYER_BOUNDS = {
        "format_variant": (0.0, 4.0),
        "preview": (1.0, 6.0),
        "near_duplicate": (2.0, 12.0),
    }
    if layer not in LAYER_BOUNDS:
        return

    # detection_meta may come back as a dict or string depending on DB driver
    if isinstance(detection_meta, str):
        try:
            meta = json.loads(detection_meta)
        except (ValueError, TypeError):
            return
    else:
        meta = detection_meta or {}

    hamming = meta.get("hamming")
    if hamming is None:
        return

    row = db.execute(
        text(
            """
            SELECT threshold FROM detection_thresholds
            WHERE catalog_id = CAST(:cid AS uuid) AND layer = :layer
        """
        ),
        {"cid": catalog_id, "layer": layer},
    ).fetchone()
    if not row:
        return

    target = (hamming + 1) if decision == "confirmed_duplicate" else (hamming - 1)
    lo, hi = LAYER_BOUNDS[layer]
    new_threshold = max(lo, min(hi, row.threshold * (1 - ALPHA) + target * ALPHA))

    db.execute(
        text(
            """
            UPDATE detection_thresholds
            SET threshold = :t,
                confirmed_count = confirmed_count + :conf,
                rejected_count = rejected_count + :rej,
                updated_at = NOW()
            WHERE catalog_id = CAST(:cid AS uuid) AND layer = :layer
        """
        ),
        {
            "t": new_threshold,
            "conf": 1 if decision == "confirmed_duplicate" else 0,
            "rej": 1 if decision == "not_duplicate" else 0,
            "cid": catalog_id,
            "layer": layer,
        },
    )


@router.get("/{catalog_id}/duplicates/stats")
def get_duplicate_stats(
    catalog_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Summary stats for the duplicate review queue."""
    get_catalog(catalog_id, db)

    by_layer = db.execute(
        text(
            """
            SELECT
                layer,
                COUNT(*) FILTER (WHERE reviewed_at IS NULL) AS pending,
                COUNT(*) FILTER (WHERE reviewed_at IS NOT NULL) AS reviewed,
                ROUND(AVG(confidence)::numeric, 3) AS avg_confidence,
                COUNT(*) FILTER (WHERE verify_carefully AND reviewed_at IS NULL) AS verify_carefully_pending
            FROM duplicate_candidates
            WHERE catalog_id = CAST(:cid AS uuid)
            GROUP BY layer
            ORDER BY layer
        """
        ),
        {"cid": str(catalog_id)},
    ).fetchall()

    thresholds = db.execute(
        text(
            """
            SELECT layer, threshold, confirmed_count, rejected_count, updated_at
            FROM detection_thresholds
            WHERE catalog_id = CAST(:cid AS uuid)
            ORDER BY layer
        """
        ),
        {"cid": str(catalog_id)},
    ).fetchall()

    suppressed = db.execute(
        text(
            """
            SELECT COUNT(*) FROM suppression_pairs sp
            WHERE EXISTS (
                SELECT 1 FROM images i WHERE i.id = sp.id_a AND i.catalog_id = CAST(:cid AS uuid)
            )
        """
        ),
        {"cid": str(catalog_id)},
    ).scalar()

    return {
        "by_layer": [dict(r._mapping) for r in by_layer],
        "thresholds": [dict(r._mapping) for r in thresholds],
        "suppressed_pairs": suppressed,
    }


@router.get("/{catalog_id}/duplicates/thresholds")
def get_thresholds(
    catalog_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Get current adaptive thresholds for all layers."""
    get_catalog(catalog_id, db)
    rows = db.execute(
        text(
            "SELECT * FROM detection_thresholds WHERE catalog_id = CAST(:cid AS uuid) ORDER BY layer"
        ),
        {"cid": str(catalog_id)},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


@router.put("/{catalog_id}/duplicates/thresholds/{layer}")
def override_threshold(
    catalog_id: uuid.UUID,
    layer: str,
    body: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Manually override a layer threshold and reset learning counts."""
    get_catalog(catalog_id, db)
    new_val = body.get("threshold")
    if new_val is None:
        raise HTTPException(status_code=422, detail="threshold field required")
    db.execute(
        text(
            """
            UPDATE detection_thresholds
            SET threshold = :t,
                confirmed_count = 0,
                rejected_count = 0,
                updated_at = NOW()
            WHERE catalog_id = CAST(:cid AS uuid) AND layer = :layer
        """
        ),
        {"t": float(new_val), "cid": str(catalog_id), "layer": layer},
    )
    db.commit()
    return {"layer": layer, "threshold": float(new_val)}


@router.get("/{catalog_id}/archive")
def list_archive(
    catalog_id: uuid.UUID,
    reason: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """List archived images with provenance info."""
    get_catalog(catalog_id, db)

    filters = ["original_catalog_id = CAST(:cid AS uuid)"]
    params: Dict[str, Any] = {"cid": str(catalog_id), "limit": limit, "offset": offset}
    if reason:
        filters.append("archive_reason = :reason")
        params["reason"] = reason

    where = " AND ".join(filters)
    rows = db.execute(
        text(
            f"""
            SELECT * FROM archived_images
            WHERE {where}
            ORDER BY archived_at DESC
            LIMIT :limit OFFSET :offset
        """
        ),
        params,
    ).fetchall()
    total = db.execute(
        text(f"SELECT COUNT(*) FROM archived_images WHERE {where}"),
        params,
    ).scalar()
    return {"total": total, "items": [dict(r._mapping) for r in rows]}


@router.post("/{catalog_id}/archive/{archived_id}/restore")
def restore_archived(
    catalog_id: uuid.UUID,
    archived_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Restore an archived image back to active status."""
    get_catalog(catalog_id, db)
    # Verify the archived image belongs to this catalog
    row = db.execute(
        text(
            "SELECT id FROM archived_images WHERE id = :id AND original_catalog_id = CAST(:cid AS uuid)"
        ),
        {"id": archived_id, "cid": str(catalog_id)},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Archived image not found")
    from ...analysis.dedup.archive import restore_image

    restore_image(archived_id, db)
    db.commit()
    return {"restored": archived_id}
