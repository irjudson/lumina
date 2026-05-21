"""Job definition: compute multi-resolution hashes for deduplication pipeline."""

import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from ..framework import ParallelJob, register_job

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLDS = {
    "format_variant": 4.0,
    "preview": 3.0,
    "near_duplicate": 8.0,
}


def discover_images_needing_hashes(
    catalog_id: str,
    images_provider: Optional[Callable] = None,
) -> List[str]:
    """Find images missing dhash_16 or dhash_32."""
    if images_provider:
        return images_provider(catalog_id)

    from lumina.db.connection import get_db_context
    from lumina.db.models import Image

    with get_db_context() as session:
        images = (
            session.query(Image.id)
            .filter(Image.catalog_id == catalog_id)
            .filter((Image.dhash_16.is_(None)) | (Image.dhash_32.is_(None)))
            .all()
        )
        return [str(row.id) for row in images]


def compute_hashes_v2(
    image_id: str,
    catalog_id: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Compute and store multi-resolution hashes for one image."""
    from lumina.analysis.hashing import compute_all_hashes_v2
    from lumina.db.connection import get_db_context
    from lumina.db.models import Image

    with get_db_context() as session:
        image = session.query(Image).filter(Image.id == image_id).first()
        if not image:
            return {"image_id": image_id, "success": False, "error": "not found"}

        try:
            hashes = compute_all_hashes_v2(image.source_path)
            image.dhash = hashes["dhash_8"]
            image.dhash_16 = hashes["dhash_16"]
            image.dhash_32 = hashes["dhash_32"]
            image.ahash = hashes["ahash"]
            image.whash = hashes["whash"]
            session.commit()
            return {"image_id": image_id, "success": True}
        except Exception as e:
            session.rollback()
            return {"image_id": image_id, "success": False, "error": str(e)}


def finalize_hash_v2(
    results: List[Dict[str, Any]],
    catalog_id: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Summarize hash computation and seed default thresholds if not set."""
    from sqlalchemy import text

    from lumina.db.connection import get_db_context
    from lumina.db.models import Catalog, DetectionThreshold

    successes = sum(1 for r in results if r.get("success"))
    failures = sum(1 for r in results if not r.get("success"))

    with get_db_context() as session:
        try:
            cat_uuid = uuid.UUID(catalog_id)
            catalog = session.query(Catalog).filter(Catalog.id == cat_uuid).first()
            if catalog:
                for layer, default in DEFAULT_THRESHOLDS.items():
                    exists = (
                        session.query(DetectionThreshold)
                        .filter(
                            DetectionThreshold.catalog_id == cat_uuid,
                            DetectionThreshold.layer == layer,
                        )
                        .first()
                    )
                    if not exists:
                        session.add(
                            DetectionThreshold(
                                catalog_id=cat_uuid,
                                layer=layer,
                                threshold=default,
                                last_run_threshold=default,
                            )
                        )
                session.commit()
        except Exception as e:
            logger.warning(f"Could not seed thresholds: {e}")
            session.rollback()

    # Mark newly-hashed images as pending_duplicate if their dhash_16 is within
    # hamming distance 8 of any existing image (the near_duplicate threshold).
    # dhash_16 is stored as a 64-char hex string; cast to bit(256) for XOR.
    near_dup_marked = 0
    with get_db_context() as session:
        try:
            result = session.execute(
                text(
                    """
                    UPDATE images AS new_img
                    SET status_id = 'pending_duplicate'
                    WHERE new_img.catalog_id = CAST(:cat_id AS uuid)
                      AND new_img.dhash_16 IS NOT NULL
                      AND new_img.status_id = 'active'
                      AND EXISTS (
                          SELECT 1 FROM images existing
                          WHERE existing.catalog_id = CAST(:cat_id AS uuid)
                            AND existing.id != new_img.id
                            AND existing.dhash_16 IS NOT NULL
                            AND bit_count(
                                ('x' || new_img.dhash_16)::bit(256)
                                # ('x' || existing.dhash_16)::bit(256)
                            ) <= 8
                      )
                    """
                ),
                {"cat_id": catalog_id},
            )
            near_dup_marked = result.rowcount or 0
            session.commit()
            if near_dup_marked:
                logger.info(
                    f"Near-dedup: marked {near_dup_marked} images as pending_duplicate"
                    f" for catalog {catalog_id}"
                )
        except Exception as e:
            logger.warning(f"Near-dedup marking failed (non-fatal): {e}")
            session.rollback()

    return {
        "catalog_id": catalog_id,
        "hashed": successes,
        "failed": failures,
        "near_dup_marked": near_dup_marked,
    }


hash_v2_job = register_job(
    ParallelJob(
        name="hash_images_v2",
        discover=discover_images_needing_hashes,
        process=compute_hashes_v2,
        finalize=finalize_hash_v2,
        batch_size=500,
    )
)
