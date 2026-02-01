"""
Parallel Burst Detection using the Coordinator Pattern.

This module implements parallel burst detection across multiple threading workers:

1. burst_coordinator: Queries images, creates batches, spawns workers
2. burst_worker: Processes a batch of images for burst detection
3. burst_finalizer: Aggregates results and creates burst records

Note: Burst detection works on time-sequential images. Batches are divided
by time ranges so workers can detect bursts within their time window.
The finalizer merges any bursts that span batch boundaries.
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import Future, as_completed
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import text

from ..analysis.burst_detector import BurstDetector, ImageInfo
from ..db import CatalogDB as CatalogDatabase
from .background_jobs import get_executor
from .coordinator import (
    CONSECUTIVE_FAILURE_THRESHOLD,
    BatchManager,
    BatchResult,
    JobCancelledException,
    cancel_and_requeue_job,
    publish_job_progress,
)

logger = logging.getLogger(__name__)


def burst_coordinator(
    job_id: str,
    catalog_id: str,
    gap_threshold: float = 2.0,
    min_burst_size: int = 3,
    batch_size: int = 5000,
) -> Dict[str, Any]:
    """
    Coordinator function for parallel burst detection.

    Args:
        job_id: Job ID for this burst detection
        catalog_id: UUID of the catalog
        gap_threshold: Maximum seconds between burst images
        min_burst_size: Minimum images to form a burst
        batch_size: Number of images per batch

    Returns:
        Final aggregated results
    """
    parent_job_id = job_id
    logger.info(
        f"[{parent_job_id}] Starting burst coordinator for catalog {catalog_id}"
    )

    batch_manager = BatchManager(catalog_id, parent_job_id, "bursts")

    try:

        # Clear existing bursts for this catalog
        with CatalogDatabase(catalog_id) as db:
            assert db.session is not None
            # First clear burst_id and burst_sequence from all images
            db.session.execute(
                text(
                    """
                    UPDATE images
                    SET burst_id = NULL, burst_sequence = NULL
                    WHERE catalog_id = :catalog_id
                """
                ),
                {"catalog_id": catalog_id},
            )
            # Then delete all burst records
            assert db.session is not None
            db.session.execute(
                text("DELETE FROM bursts WHERE catalog_id = :catalog_id"),
                {"catalog_id": catalog_id},
            )
            assert db.session is not None
            db.session.commit()

            # Get all images with timestamps (sorted by time)
            assert db.session is not None
            result = db.session.execute(
                text(
                    """
                    SELECT id,
                           (dates->>'selected_date')::timestamp as date_taken,
                           metadata->>'camera_make' as camera_make,
                           metadata->>'camera_model' as camera_model,
                           quality_score,
                           source_path,
                           (metadata->>'gps_latitude')::double precision as latitude,
                           (metadata->>'gps_longitude')::double precision as longitude,
                           metadata->>'geohash' as geohash
                    FROM images
                    WHERE catalog_id = :catalog_id
                    AND dates->>'selected_date' IS NOT NULL
                    AND (dates->>'confidence')::int >= 70
                    ORDER BY (dates->>'selected_date')::timestamp
                """
                ),
                {"catalog_id": catalog_id},
            )

            # Build image data list: (id, timestamp_str, camera_make, camera_model, quality, source_path, lat, lon, geohash)
            image_data = []
            for row in result.fetchall():
                image_data.append(
                    (
                        str(row[0]),
                        row[1].isoformat() if row[1] else None,
                        row[2],
                        row[3],
                        row[4] or 0.0,
                        row[5],  # source_path
                        row[6],  # latitude
                        row[7],  # longitude
                        row[8],  # geohash
                    )
                )

        total_images = len(image_data)
        logger.info(f"[{parent_job_id}] Found {total_images} images with timestamps")

        if total_images == 0:
            logger.info(f"[{parent_job_id}] No images with timestamps found")
            return {
                "status": "completed",
                "job_type": "bursts",
                "catalog_id": catalog_id,
                "bursts_detected": 0,
                "total_burst_images": 0,
                "message": "No images with timestamps found",
            }

        # Create batches
        with CatalogDatabase(catalog_id) as db:
            batch_ids = batch_manager.create_batches(
                work_items=image_data,
                batch_size=batch_size,
                db=db,
            )

            # Get total batches from progress
            total_batches = len(batch_ids)
            logger.info(f"[{parent_job_id}] Created {total_batches} batches")

            # Publish initial progress
            publish_job_progress(
                parent_job_id,
                batch_manager.get_progress(db),
                f"Starting burst detection for {total_images:,} images",
                phase="starting",
            )

        # Execute workers in ThreadPoolExecutor
        executor = get_executor()
        futures: Dict[Future, str] = {}

        for batch_id in batch_ids:
            future = executor.submit(
                burst_worker,
                catalog_id=catalog_id,
                batch_id=batch_id,
                parent_job_id=parent_job_id,
                gap_threshold=gap_threshold,
                min_burst_size=min_burst_size,
            )
            futures[future] = batch_id

        # Wait for all workers to complete and collect results
        worker_results: List[Dict[str, Any]] = []
        for future in as_completed(futures):
            try:
                worker_result = future.result()
                worker_results.append(worker_result)
            except Exception as e:
                batch_id = futures[future]
                logger.error(f"Worker for batch {batch_id} raised exception: {e}")
                worker_results.append(
                    {
                        "batch_id": batch_id,
                        "status": "failed",
                        "error": str(e),
                    }
                )

        logger.info(
            f"[{parent_job_id}] All {total_batches} workers complete, running finalizer"
        )

        # Run finalizer
        final_result = burst_finalizer(
            worker_results=worker_results,
            catalog_id=catalog_id,
            parent_job_id=parent_job_id,
            gap_threshold=gap_threshold,
            min_burst_size=min_burst_size,
        )

        return final_result

    except Exception as e:
        logger.error(f"[{parent_job_id}] Coordinator failed: {e}", exc_info=True)
        raise


def burst_worker(
    catalog_id: str,
    batch_id: str,
    parent_job_id: str,
    gap_threshold: float,
    min_burst_size: int,
) -> Dict[str, Any]:
    """Worker function that detects bursts within a batch of images.

    Args:
        catalog_id: Catalog UUID
        batch_id: UUID of the batch to process
        parent_job_id: Coordinator's job ID (for progress publishing)
        gap_threshold: Maximum seconds between burst images
        min_burst_size: Minimum images to form a burst

    Returns:
        BatchResult dictionary
    """
    import threading

    worker_id = f"thread-{threading.get_ident()}"
    logger.info(f"[{worker_id}] Starting burst worker for batch {batch_id}")

    batch_manager = BatchManager(catalog_id, parent_job_id, "bursts")

    try:
        with CatalogDatabase(catalog_id) as db:
            batch_data = batch_manager.claim_batch(batch_id, worker_id, db)

        if not batch_data:
            logger.warning(f"[{worker_id}] Batch {batch_id} already claimed")
            return {
                "batch_id": batch_id,
                "status": "skipped",
                "reason": "already_claimed",
            }

        batch_number = batch_data["batch_number"]
        total_batches = batch_data["total_batches"]
        image_data = batch_data[
            "work_items"
        ]  # List of (id, timestamp, camera_make, camera_model, quality, source_path, lat, lon, geohash)
        items_count = batch_data["items_count"]

        logger.info(
            f"[{worker_id}] Processing batch {batch_number + 1}/{total_batches} ({items_count} images)"
        )

        result = BatchResult(batch_id=batch_id, batch_number=batch_number)

        # Convert to ImageInfo objects
        images = []
        for item in image_data:
            (
                img_id,
                timestamp_str,
                camera_make,
                camera_model,
                quality,
                source_path,
                latitude,
                longitude,
                geohash,
            ) = item
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(timestamp_str)
                    images.append(
                        ImageInfo(
                            image_id=img_id,
                            timestamp=timestamp,
                            camera_make=camera_make,
                            camera_model=camera_model,
                            quality_score=quality,
                            source_path=source_path,
                            latitude=latitude,
                            longitude=longitude,
                            geohash=geohash,
                        )
                    )
                except ValueError:
                    logger.warning(
                        f"Invalid timestamp for image {img_id}: {timestamp_str}"
                    )

        # Check for cancellation before processing
        if batch_manager.is_cancelled(batch_id):
            logger.warning(
                f"[{worker_id}] Batch {batch_id} cancelled before burst detection"
            )
            raise JobCancelledException(
                f"Job cancelled before processing batch {batch_number + 1}"
            )

        # Detect bursts within this batch
        detector = BurstDetector(
            gap_threshold_seconds=gap_threshold,
            min_burst_size=min_burst_size,
        )
        bursts = detector.detect_bursts(images)

        logger.info(
            f"[{worker_id}] Detected {len(bursts)} bursts in batch {batch_number + 1}"
        )

        # Store burst data in results for the finalizer to aggregate
        burst_data = []
        for burst in bursts:
            burst_data.append(
                {
                    "image_ids": [img.image_id for img in burst.images],
                    "start_time": (
                        burst.start_time.isoformat() if burst.start_time else None
                    ),
                    "end_time": burst.end_time.isoformat() if burst.end_time else None,
                    "camera_make": burst.camera_make,
                    "camera_model": burst.camera_model,
                    "best_image_id": burst.best_image_id,
                    "selection_method": burst.selection_method,
                }
            )

        result.processed_count = len(images)
        result.success_count = len(bursts)
        result.results = {
            "bursts": burst_data,
            "first_timestamp": images[0].timestamp.isoformat() if images else None,
            "last_timestamp": images[-1].timestamp.isoformat() if images else None,
        }

        # Mark batch complete
        with CatalogDatabase(catalog_id) as db:
            batch_manager.complete_batch(batch_id, result, db)
            progress = batch_manager.get_progress(db)
            publish_job_progress(
                parent_job_id,
                progress,
                f"Batch {batch_number + 1}/{total_batches} complete ({len(bursts)} bursts)",
                phase="processing",
            )

        logger.info(
            f"[{worker_id}] Batch {batch_number + 1} complete: {len(bursts)} bursts detected"
        )

        return {
            "batch_id": batch_id,
            "batch_number": batch_number,
            "status": "completed",
            "bursts_count": len(bursts),
            "images_processed": len(images),
            "bursts": burst_data,
        }

    except JobCancelledException as e:
        logger.warning(f"[{worker_id}] Worker cancelled: {e}")
        return {
            "batch_id": batch_id,
            "batch_number": batch_number if "batch_number" in locals() else 0,
            "status": "cancelled",
            "bursts_count": 0,
            "images_processed": 0,
            "message": str(e),
        }

    except Exception as e:
        logger.error(f"[{worker_id}] Worker failed: {e}", exc_info=True)
        try:
            batch_manager.fail_batch(batch_id, str(e))
        except Exception:
            pass
        return {"batch_id": batch_id, "status": "failed", "error": str(e)}


def burst_finalizer(
    worker_results: List[Dict[str, Any]],
    catalog_id: str,
    parent_job_id: str,
    gap_threshold: float,
    min_burst_size: int,
) -> Dict[str, Any]:
    """Finalizer function that aggregates burst detection results and saves to database.

    Args:
        worker_results: List of results from all worker tasks
        catalog_id: Catalog UUID
        parent_job_id: Coordinator's job ID
        gap_threshold: Maximum seconds between burst images
        min_burst_size: Minimum images to form a burst

    Returns:
        Final aggregated results
    """
    logger.info(f"[{parent_job_id}] Running burst finalizer")

    # Log worker results summary
    total_workers = len(worker_results)
    successful_workers = sum(
        1 for r in worker_results if r.get("status") == "completed"
    )
    logger.info(
        f"[{parent_job_id}] Worker results: {successful_workers}/{total_workers} completed"
    )

    batch_manager = BatchManager(catalog_id, parent_job_id, "bursts")

    try:

        # Collect all bursts from workers, ordered by batch number
        all_bursts = []
        sorted_results = sorted(
            [wr for wr in worker_results if wr.get("status") == "completed"],
            key=lambda x: x.get("batch_number", 0),
        )

        for wr in sorted_results:
            bursts = wr.get("bursts", [])
            all_bursts.extend(bursts)

        logger.info(
            f"[{parent_job_id}] Collected {len(all_bursts)} bursts from workers"
        )

        # Check for bursts that span batch boundaries and merge them
        # A burst at the end of batch N might continue into batch N+1
        merged_bursts = _merge_adjacent_bursts(
            all_bursts, gap_threshold, min_burst_size
        )

        logger.info(f"[{parent_job_id}] After merging: {len(merged_bursts)} bursts")

        total_burst_images = 0
        with CatalogDatabase(catalog_id) as db:
            for burst in merged_bursts:
                burst_id = str(uuid.uuid4())
                image_ids = burst["image_ids"]
                total_burst_images += len(image_ids)

                # Calculate duration
                start_time = datetime.fromisoformat(burst["start_time"])
                end_time = datetime.fromisoformat(burst["end_time"])
                duration = (end_time - start_time).total_seconds()

                # Insert burst record
                assert db.session is not None
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
                        "image_count": len(image_ids),
                        "start_time": start_time,
                        "end_time": end_time,
                        "duration": duration,
                        "camera_make": burst.get("camera_make"),
                        "camera_model": burst.get("camera_model"),
                        "best_image_id": burst.get("best_image_id"),
                        "selection_method": burst.get("selection_method"),
                    },
                )

                # Update images with burst_id and sequence
                for seq, img_id in enumerate(image_ids):
                    assert db.session is not None
                    db.session.execute(
                        text(
                            """
                            UPDATE images
                            SET burst_id = :burst_id, burst_sequence = :seq
                            WHERE id = :image_id
                        """
                        ),
                        {
                            "burst_id": burst_id,
                            "image_id": img_id,
                            "seq": seq,
                        },
                    )

            assert db.session is not None
            db.session.commit()

        with CatalogDatabase(catalog_id) as db:
            # Get final statistics
            progress = batch_manager.get_progress(db)

        failed_batches = sum(1 for wr in worker_results if wr.get("status") == "failed")

        # If there were too many failed batches, auto-requeue to continue
        if failed_batches >= CONSECUTIVE_FAILURE_THRESHOLD:
            logger.warning(
                f"[{parent_job_id}] {failed_batches} batches failed, auto-requeuing continuation"
            )

            cancel_and_requeue_job(
                parent_job_id=parent_job_id,
                catalog_id=catalog_id,
                job_type="bursts",
                task_name="burst_coordinator",
                task_kwargs={
                    "catalog_id": catalog_id,
                    "gap_threshold": gap_threshold,
                    "min_burst_size": min_burst_size,
                    "batch_size": 5000,  # default batch size
                },
                reason=f"{failed_batches} batch failures",
                processed_so_far=len(merged_bursts),
            )

            return {
                "status": "requeued",
                "job_type": "bursts",
                "catalog_id": catalog_id,
                "bursts_detected": len(merged_bursts),
                "total_burst_images": total_burst_images,
                "failed_batches": failed_batches,
                "message": f"Job requeued due to {failed_batches} batch failures",
            }

        final_result = {
            "status": "completed" if failed_batches == 0 else "completed_with_errors",
            "job_type": "bursts",
            "catalog_id": catalog_id,
            "bursts_detected": len(merged_bursts),
            "total_burst_images": total_burst_images,
            "items_processed": progress.success_items + progress.error_items,
            "items_success": progress.success_items,
            "items_failed": progress.error_items,
            "total_batches": progress.total_batches,
            "failed_batches": failed_batches,
        }

        # Publish final progress
        publish_job_progress(
            parent_job_id,
            progress,
            f"Burst detection complete: {len(merged_bursts)} bursts detected",
            phase="completed",
        )

        logger.info(
            f"[{parent_job_id}] Burst detection complete: {len(merged_bursts)} bursts, {total_burst_images} images"
        )

        return final_result

    except Exception as e:
        logger.error(f"[{parent_job_id}] Finalizer failed: {e}", exc_info=True)
        raise


def _merge_adjacent_bursts(
    bursts: List[Dict[str, Any]],
    gap_threshold: float,
    min_burst_size: int,
) -> List[Dict[str, Any]]:
    """
    Merge bursts that span batch boundaries.

    If a burst at the end of batch N ends within gap_threshold seconds
    of when a burst at the start of batch N+1 begins, and they have
    the same camera, merge them.
    """
    if len(bursts) <= 1:
        return bursts

    merged = []
    current_burst = None

    for burst in bursts:
        if current_burst is None:
            current_burst = burst.copy()
            continue

        # Check if we should merge with current_burst
        current_end = datetime.fromisoformat(current_burst["end_time"])
        next_start = datetime.fromisoformat(burst["start_time"])
        gap = (next_start - current_end).total_seconds()

        # Same camera and within gap threshold?
        same_camera = current_burst.get("camera_make") == burst.get(
            "camera_make"
        ) and current_burst.get("camera_model") == burst.get("camera_model")

        if same_camera and gap <= gap_threshold:
            # Merge the bursts
            current_burst["image_ids"].extend(burst["image_ids"])
            current_burst["end_time"] = burst["end_time"]
            # Keep the best image with highest quality (would need quality info)
            # For now, keep the existing best_image_id from the first burst
        else:
            # Save current burst and start new one
            if len(current_burst["image_ids"]) >= min_burst_size:
                merged.append(current_burst)
            current_burst = burst.copy()

    # Don't forget the last burst
    if current_burst and len(current_burst["image_ids"]) >= min_burst_size:
        merged.append(current_burst)

    return merged
