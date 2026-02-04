"""Job implementations using the new background job system."""

import logging
from pathlib import Path
from typing import Any, Callable, Dict

from ..analysis.scanner import ImageScanner
from ..db import CatalogDB as CatalogDatabase
from .background_jobs import update_job_status

logger = logging.getLogger(__name__)


def scan_analyze_job(
    catalog_id: str,
    source_paths: list[str],
    job_id: str,
    workers: int = 4,
    detect_duplicates: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Run catalog scan and analysis."""
    try:
        # Convert source paths to Path objects
        source_dirs = [Path(p) for p in source_paths]

        # Open catalog database
        with CatalogDatabase(catalog_id) as catalog_db:
            # Create scanner
            scanner = ImageScanner(
                catalog_db,
                workers=workers,
                perf_tracker=None,  # TODO: Add progress tracking
            )

            # Update progress to indicate scanning started
            update_job_status(
                job_id,
                "PROGRESS",
                progress={"current": 0, "total": 0, "percent": 0, "phase": "scanning"},
            )

            # Run scan
            scanner.scan_directories(source_dirs)

            # Final result
            result = {
                "files_added": scanner.files_added,
                "files_updated": scanner.files_updated,
                "files_skipped": scanner.files_skipped,
                "files_error": scanner.files_error,
                "total_bytes": scanner.total_bytes,
                "catalog_id": catalog_id,
            }

            return result

    except Exception:
        logger.exception(f"Scan job {job_id} failed")
        raise


def detect_duplicates_job(
    catalog_id: str,
    job_id: str,
    similarity_threshold: int = 5,
    recompute_hashes: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Run duplicate detection using perceptual hashing.

    Args:
        catalog_id: The catalog UUID
        job_id: The background job ID
        similarity_threshold: Maximum Hamming distance for similar images (default: 5)
        recompute_hashes: Force recomputation of perceptual hashes
        **kwargs: Additional options

    Returns:
        Dict with duplicate detection results
    """
    from ..analysis.duplicate_detector import DuplicateDetector

    try:
        with CatalogDatabase(catalog_id) as catalog_db:

            def progress_callback(current: int, total: int, message: str) -> None:
                """Update job progress."""
                percent = int((current / total) * 100) if total > 0 else 0
                update_job_status(
                    job_id,
                    "PROGRESS",
                    progress={
                        "current": current,
                        "total": total,
                        "percent": percent,
                        "phase": "detecting_duplicates",
                        "message": message,
                    },
                )

            update_job_status(
                job_id,
                "PROGRESS",
                progress={
                    "current": 0,
                    "total": 100,
                    "percent": 0,
                    "phase": "initializing",
                },
            )

            # Create detector with progress callback
            detector = DuplicateDetector(
                catalog=catalog_db,
                similarity_threshold=similarity_threshold,
                num_workers=1,  # Use single-threaded mode for job worker
                progress_callback=progress_callback,
            )

            # Run detection (results stored in detector.duplicate_groups)
            detector.detect_duplicates(recompute_hashes=recompute_hashes)

            # Save results to database
            detector.save_duplicate_groups()
            detector.save_problematic_files()

            # Get statistics
            stats = detector.get_statistics()

            result = {
                "duplicates_found": stats["total_images_in_groups"],
                "groups_created": stats["total_groups"],
                "redundant_images": stats["total_redundant"],
                "groups_needing_review": stats["groups_needing_review"],
                "catalog_id": catalog_id,
            }

            return result

    except Exception:
        logger.exception(f"Duplicate detection job {job_id} failed")
        raise


def generate_thumbnails_job(
    catalog_id: str, job_id: str, force: bool = False, **kwargs: Any
) -> Dict[str, Any]:
    """Generate thumbnails for catalog images."""
    from .parallel_thumbnails import thumbnail_coordinator

    return thumbnail_coordinator(
        job_id=job_id,
        catalog_id=catalog_id,
        force=force,
    )


def detect_bursts_job(
    catalog_id: str,
    job_id: str,
    gap_threshold: float = 2.0,
    min_burst_size: int = 3,
    batch_size: int = 5000,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Detect burst photo sequences."""
    from .parallel_bursts import burst_coordinator

    return burst_coordinator(
        job_id=job_id,
        catalog_id=catalog_id,
        gap_threshold=gap_threshold,
        min_burst_size=min_burst_size,
        batch_size=batch_size,
    )


def auto_tag_job(
    catalog_id: str,
    job_id: str,
    backend: str = "openclip",
    model: str = None,
    threshold: float = 0.25,
    max_tags: int = 10,
    tag_mode: str = "untagged_only",
    batch_size: int = 500,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Auto-tag images using AI models."""
    from .parallel_tagging import tagging_coordinator

    return tagging_coordinator(
        job_id=job_id,
        catalog_id=catalog_id,
        backend=backend,
        model=model,
        threshold=threshold,
        max_tags=max_tags,
        tag_mode=tag_mode,
        batch_size=batch_size,
    )


# Job registry
JOB_FUNCTIONS: Dict[str, Callable[..., Any]] = {
    "scan": scan_analyze_job,
    "analyze": scan_analyze_job,
    "detect_duplicates": detect_duplicates_job,
    "generate_thumbnails": generate_thumbnails_job,
    "detect_bursts": detect_bursts_job,
    "auto_tag": auto_tag_job,
}
