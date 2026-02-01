"""Job implementations using the new background job system."""

import logging
import uuid
from pathlib import Path
from typing import Any, Callable, Dict

from sqlalchemy import text

from ..analysis.burst_detector import BurstDetector, ImageInfo
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
    catalog_id: str, job_id: str, similarity_threshold: int = 5, **kwargs: Any
) -> Dict[str, Any]:
    """Run duplicate detection."""
    try:
        with CatalogDatabase(catalog_id) as _catalog_db:  # noqa: F841
            update_job_status(
                job_id,
                "PROGRESS",
                progress={
                    "current": 0,
                    "total": 100,
                    "percent": 0,
                    "phase": "detecting_duplicates",
                },
            )

            # TODO: Implement duplicate detection
            # For now, just a stub

            result = {
                "duplicates_found": 0,
                "groups_created": 0,
                "catalog_id": catalog_id,
            }

            return result

    except Exception:
        logger.exception(f"Duplicate detection job {job_id} failed")
        raise


def generate_thumbnails_job(
    catalog_id: str, job_id: str, **kwargs: Any
) -> Dict[str, Any]:
    """Generate thumbnails for catalog images."""
    try:
        with CatalogDatabase(catalog_id) as _catalog_db:  # noqa: F841
            update_job_status(
                job_id,
                "PROGRESS",
                progress={
                    "current": 0,
                    "total": 100,
                    "percent": 0,
                    "phase": "generating_thumbnails",
                },
            )

            # TODO: Implement thumbnail generation

            result = {"thumbnails_generated": 0, "catalog_id": catalog_id}

            return result

    except Exception:
        logger.exception(f"Thumbnail generation job {job_id} failed")
        raise


def detect_bursts_job(
    catalog_id: str,
    job_id: str,
    gap_threshold: float = 2.0,
    min_burst_size: int = 3,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Detect burst photo sequences."""
    try:
        logger.info(f"[{job_id}] Starting burst detection for catalog {catalog_id}")

        update_job_status(
            job_id,
            "PROGRESS",
            progress={"current": 0, "total": 1, "percent": 0, "phase": "init"},
        )

        with CatalogDatabase(catalog_id) as db:
            assert db.session is not None  # Always true inside context manager
            # Clear existing bursts for this catalog
            db.session.execute(
                text("DELETE FROM bursts WHERE catalog_id = :catalog_id"),
                {"catalog_id": catalog_id},
            )
            db.session.commit()

            # Load images with timestamps - only those with proper date extraction
            result = db.session.execute(
                text(
                    """
                    SELECT id,
                           (dates->>'selected_date')::timestamp as date_taken,
                           metadata->>'camera_make' as camera_make,
                           metadata->>'camera_model' as camera_model,
                           quality_score
                    FROM images
                    WHERE catalog_id = :catalog_id
                    AND dates->>'selected_date' IS NOT NULL
                    AND (dates->>'confidence')::int >= 70
                    ORDER BY (dates->>'selected_date')::timestamp
                """
                ),
                {"catalog_id": catalog_id},
            )

            images = [
                ImageInfo(
                    image_id=str(row[0]),
                    timestamp=row[1],
                    camera_make=row[2],
                    camera_model=row[3],
                    quality_score=row[4] or 0.0,
                )
                for row in result.fetchall()
            ]

            logger.info(f"[{job_id}] Loaded {len(images)} images with timestamps")

            update_job_status(
                job_id,
                "PROGRESS",
                progress={
                    "current": 1,
                    "total": 2,
                    "percent": 50,
                    "phase": "detecting",
                    "images_loaded": len(images),
                },
            )

            # Detect bursts
            detector = BurstDetector(
                gap_threshold_seconds=gap_threshold,
                min_burst_size=min_burst_size,
            )
            bursts = detector.detect_bursts(images)

            logger.info(f"[{job_id}] Detected {len(bursts)} bursts")

            update_job_status(
                job_id,
                "PROGRESS",
                progress={
                    "current": 1,
                    "total": 2,
                    "percent": 75,
                    "phase": "saving",
                    "bursts_detected": len(bursts),
                },
            )

            # Save bursts to database
            total_burst_images = 0
            for burst in bursts:
                burst_id = str(uuid.uuid4())

                # Insert burst record
                db.session.execute(
                    text(
                        """
                        INSERT INTO bursts (
                            id, catalog_id, image_count, start_time, end_time,
                            duration_seconds, camera_make, camera_model,
                            best_image_id, selection_method, created_at
                        ) VALUES (
                            :id, :catalog_id, :image_count, :start_time, :end_time,
                            :duration, :camera_make, :camera_model,
                            :best_image_id, :selection_method, NOW()
                        )
                    """
                    ),
                    {
                        "id": burst_id,
                        "catalog_id": catalog_id,
                        "image_count": len(burst.images),
                        "start_time": burst.start_time,
                        "end_time": burst.end_time,
                        "duration": burst.duration_seconds,
                        "camera_make": burst.camera_make,
                        "camera_model": burst.camera_model,
                        "best_image_id": burst.best_image_id,
                        "selection_method": "quality",
                    },
                )

                # Update images with burst_id and sequence
                for seq, image in enumerate(burst.images):
                    db.session.execute(
                        text(
                            """
                            UPDATE images
                            SET burst_id = :burst_id, burst_sequence = :sequence
                            WHERE id = :image_id
                        """
                        ),
                        {
                            "burst_id": burst_id,
                            "sequence": seq,
                            "image_id": image.image_id,
                        },
                    )
                    total_burst_images += 1

            db.session.commit()

            job_result = {
                "status": "completed",
                "bursts_detected": len(bursts),
                "images_processed": len(images),
                "total_burst_images": total_burst_images,
                "catalog_id": catalog_id,
            }

            logger.info(
                f"[{job_id}] Burst detection complete: {len(bursts)} bursts, "
                f"{total_burst_images} images"
            )

            return job_result

    except Exception:
        logger.exception(f"Burst detection job {job_id} failed")
        raise


def auto_tag_job(
    catalog_id: str,
    job_id: str,
    backend: str = "openclip",
    model: str = None,
    threshold: float = 0.25,
    max_tags: int = 10,
    max_images: int = None,
    tag_mode: str = "untagged_only",
    continue_pipeline: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Auto-tag images using AI models.

    TODO: Full implementation pending conversion from Celery parallel system.
    This is a stub to maintain API compatibility during migration.
    """
    try:
        logger.info(
            f"[{job_id}] Starting auto-tag for catalog {catalog_id} "
            f"with {backend} backend (mode={tag_mode})"
        )

        update_job_status(
            job_id,
            "PROGRESS",
            progress={
                "current": 0,
                "total": 100,
                "percent": 0,
                "phase": "init",
                "backend": backend,
            },
        )

        # TODO: Implement full auto-tagging logic from tasks.py auto_tag_task
        # For now, return stub result
        result = {
            "status": "completed",
            "images_tagged": 0,
            "tags_added": 0,
            "backend": backend,
            "catalog_id": catalog_id,
        }

        logger.info(f"[{job_id}] Auto-tag stub completed")
        return result

    except Exception:
        logger.exception(f"Auto-tag job {job_id} failed")
        raise


# Job registry
JOB_FUNCTIONS: Dict[str, Callable[..., Any]] = {
    "scan": scan_analyze_job,
    "analyze": scan_analyze_job,
    "detect_duplicates": detect_duplicates_job,
    "generate_thumbnails": generate_thumbnails_job,
    "detect_bursts": detect_bursts_job,
    "auto_tag": auto_tag_job,
}
