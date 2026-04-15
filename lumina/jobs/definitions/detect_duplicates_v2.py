"""Job: detect_duplicates_v2 — runs all 5 detection layers sequentially."""

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ...analysis.dedup.layers.l1_exact import detect_exact
from ...analysis.dedup.layers.l2_reimport import detect_reimport
from ...analysis.dedup.layers.l3_format_variant import detect_format_variants
from ...analysis.dedup.layers.l4_preview import detect_previews
from ...analysis.dedup.layers.l5_near_duplicate import detect_near_duplicates
from ...analysis.dedup.pipeline import (
    filter_suppressed,
    load_suppression_set,
    upsert_candidate,
)
from ..framework import ParallelJob, register_job

logger = logging.getLogger(__name__)


class ReprocessMode(Enum):
    NEW_IMAGES_ONLY = "new"
    THRESHOLD_CHANGED = "layer"
    FULL_RESCAN = "full"


DEFAULT_THRESHOLDS = {
    "format_variant": 4.0,
    "preview": 3.0,
    "near_duplicate": 8.0,
}


def _load_images(catalog_id: str, session, mode: str = "full") -> List[Dict]:
    """Load images from database for detection.

    For mode='new', returns only images that haven't appeared in any
    duplicate_candidates row yet (never been through detection).
    For 'full' and 'layer', returns all active images.
    """
    base_query = """
        SELECT id, source_path, checksum, format, dhash, ahash, whash,
               dhash_16, dhash_32, width, height, capture_time,
               camera_make, camera_model, created_at, metadata
        FROM images
        WHERE catalog_id = CAST(:cid AS uuid) AND status_id = 'active'
    """
    if mode == "new":
        base_query += """
            AND NOT EXISTS (
                SELECT 1 FROM duplicate_candidates dc
                WHERE (dc.image_id_a = images.id OR dc.image_id_b = images.id)
                AND dc.catalog_id = CAST(:cid AS uuid)
            )
        """
    rows = session.execute(text(base_query), {"cid": catalog_id}).fetchall()
    return [dict(r._mapping) for r in rows]


def _load_thresholds(catalog_id: str, session) -> Dict[str, float]:
    rows = session.execute(
        text(
            "SELECT layer, threshold FROM detection_thresholds"
            " WHERE catalog_id = CAST(:cid AS uuid)"
        ),
        {"cid": catalog_id},
    ).fetchall()
    thresholds = dict(DEFAULT_THRESHOLDS)
    for row in rows:
        thresholds[row.layer] = row.threshold
    return thresholds


def _clear_unreviewed(catalog_id: str, layer: Optional[str], session) -> None:
    """Clear unreviewed candidates (never touches reviewed ones)."""
    params: Dict[str, Any] = {"cid": catalog_id}
    layer_filter = ""
    if layer:
        layer_filter = " AND layer = :layer"
        params["layer"] = layer
    session.execute(
        text(
            f"DELETE FROM duplicate_candidates"
            f" WHERE catalog_id = CAST(:cid AS uuid) AND reviewed_at IS NULL {layer_filter}"
        ),
        params,
    )


def discover_catalog(catalog_id: str, **kwargs) -> List[str]:
    """Discovery: returns a single-item list so finalize runs once."""
    return [catalog_id]


def run_all_layers(
    item_catalog_id: str,
    catalog_id: str,
    mode: str = "full",
    layer: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Process: run all detection layers for the catalog.

    The framework calls process(item, catalog_id=catalog_id, ...).
    Since discover returns [catalog_id], item_catalog_id == catalog_id.
    """
    from lumina.db.connection import get_db_context

    with get_db_context() as session:
        # Clear stale candidates based on mode
        if mode == "full":
            _clear_unreviewed(catalog_id, None, session)
        elif mode == "layer" and layer:
            _clear_unreviewed(catalog_id, layer, session)
        session.commit()

        images = _load_images(catalog_id, session, mode)
        thresholds = _load_thresholds(catalog_id, session)
        suppressed = load_suppression_set(catalog_id, session)

        counts: Dict[str, int] = {}

        layer_fns = [
            ("exact", lambda imgs, t: detect_exact(imgs)),
            ("reimport", lambda imgs, t: detect_reimport(imgs)),
            (
                "format_variant",
                lambda imgs, t: detect_format_variants(
                    imgs, t.get("format_variant", 4.0)
                ),
            ),
            ("preview", lambda imgs, t: detect_previews(imgs, t.get("preview", 3.0))),
            (
                "near_duplicate",
                lambda imgs, t: detect_near_duplicates(
                    imgs, t.get("near_duplicate", 8.0)
                ),
            ),
        ]

        # If targeted layer reprocess, only run that layer
        if mode == "layer" and layer:
            layer_fns = [(name, fn) for name, fn in layer_fns if name == layer]

        for layer_name, layer_fn in layer_fns:
            n = 0
            for candidate in filter_suppressed(
                layer_fn(images, thresholds), suppressed
            ):
                upsert_candidate(candidate, session)
                n += 1
            session.commit()
            counts[layer_name] = n
            logger.info(f"Layer {layer_name}: {n} candidates")

        # Update last_run_threshold for drift detection
        for lyr, default in DEFAULT_THRESHOLDS.items():
            current = thresholds.get(lyr, default)
            session.execute(
                text(
                    "UPDATE detection_thresholds"
                    " SET last_run_threshold = :t"
                    " WHERE catalog_id = CAST(:cid AS uuid) AND layer = :layer"
                ),
                {"t": current, "cid": catalog_id, "layer": lyr},
            )
        session.commit()

        return {"catalog_id": catalog_id, "mode": mode, "candidates_by_layer": counts}


def finalize_detection(
    results: List[Dict], catalog_id: str, **kwargs
) -> Dict[str, Any]:
    total = sum(sum(r.get("candidates_by_layer", {}).values()) for r in results)
    return {"catalog_id": catalog_id, "total_candidates": total, "results": results}


detect_duplicates_v2_job = register_job(
    ParallelJob(
        name="detect_duplicates_v2",
        discover=discover_catalog,
        process=run_all_layers,
        finalize=finalize_detection,
        batch_size=1,
    )
)
