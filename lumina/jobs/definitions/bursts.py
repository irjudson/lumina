"""Burst detection job definition.

Detects sequences of rapidly captured images.
"""

from typing import Any, Callable, Dict, List, Optional

from ..framework import ParallelJob, register_job


def discover_images_for_bursts(
    catalog_id: str,
    images_provider: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    """Get all images with timestamps for burst detection.

    Returns images as dicts since burst detection needs multiple fields.

    Args:
        catalog_id: The catalog UUID
        images_provider: Optional function to get images with timestamps
                        (defaults to database lookup)

    Returns:
        List of image dicts with id, timestamp, camera fields
    """
    if images_provider:
        return images_provider(catalog_id)

    # Default: use database lookup
    from lumina.db.models import Image
    from lumina.db.session import get_db_session

    with get_db_session() as session:
        images = (
            session.query(Image)
            .filter(Image.catalog_id == catalog_id)
            .filter(Image.capture_time.isnot(None))
            .all()
        )
        return [
            {
                "id": str(img.id),
                "timestamp": img.capture_time,
                "camera": img.camera_model or "unknown",
                "quality_score": img.quality_score,
            }
            for img in images
        ]


def detect_catalog_bursts(
    images: List[Dict[str, Any]],
    catalog_id: str,
    save_bursts: Optional[Callable[[str, List[Dict[str, Any]]], None]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Detect bursts in catalog images.

    Note: This is a single-pass algorithm, not per-item processing.
    The job framework calls this once with all images.

    Args:
        images: List of image dicts with timestamp and camera fields
        catalog_id: The catalog UUID
        save_bursts: Optional function to save burst groups
        **kwargs: Additional options (gap_threshold, min_size)

    Returns:
        Summary of bursts detected
    """
    from lumina.analysis.bursts import detect_bursts, select_best_in_burst

    # Detect bursts
    bursts = detect_bursts(
        images,
        gap_threshold=kwargs.get("gap_threshold", 1.0),
        min_size=kwargs.get("min_size", 3),
    )

    # Select best image in each burst
    for burst in bursts:
        burst_images = [img for img in images if img["id"] in burst["image_ids"]]
        burst["best_image_id"] = select_best_in_burst(burst_images)

    # Save to database if provider given
    if save_bursts:
        save_bursts(catalog_id, bursts)

    return {
        "bursts_detected": len(bursts),
        "images_in_bursts": sum(len(b["image_ids"]) for b in bursts),
    }


# Bursts job is single-pass, not parallel per-item
# Use batch_size = total to process all at once
bursts_job: ParallelJob[Dict[str, Any]] = register_job(
    ParallelJob(
        name="detect_bursts",
        discover=discover_images_for_bursts,
        process=detect_catalog_bursts,
        finalize=None,  # Processing function handles everything
        batch_size=100000,  # Large batch = single pass
        max_workers=1,  # Single worker for this algorithm
    )
)
