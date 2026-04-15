"""Warehouse task definitions and need assessment logic."""

import logging
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

from sqlalchemy import text

from ..db import get_db_context

logger = logging.getLogger(__name__)


@dataclass
class WarehouseTask:
    """Definition of a warehouse automation task."""

    task_type: str  # Unique identifier
    job_type: str  # What job to submit
    priority: int  # Priority level (10-40 for warehouse)
    need_assessment: Callable[
        [str, Dict], Tuple[bool, int, Dict]
    ]  # Assessment function
    default_interval_minutes: int  # How often to check
    default_threshold: Dict  # Default threshold configuration


def check_low_confidence_tags(catalog_id: str, config: Dict) -> Tuple[bool, int, Dict]:
    """Check if there are images with low confidence tags that need retagging.

    Args:
        catalog_id: Catalog ID
        config: Configuration dict with threshold settings

    Returns:
        Tuple of (should_run, count, job_parameters)
    """
    threshold = config.get("confidence_threshold", 0.3)
    min_count = config.get("min_images", 10)

    try:
        with get_db_context() as db:
            result = db.execute(
                text(
                    """
                    SELECT COUNT(DISTINCT image_id)
                    FROM image_tags
                    WHERE image_id IN (
                        SELECT id FROM images WHERE catalog_id = :catalog_id
                    )
                    AND confidence < :threshold
                """
                ),
                {"catalog_id": catalog_id, "threshold": threshold},
            )
            count = result.scalar() or 0

            if count >= min_count:
                return (
                    True,
                    count,
                    {
                        "tag_mode": "low_confidence_only",
                        "threshold": threshold,
                        "backend": "openclip",
                    },
                )

    except Exception as e:
        logger.error(f"Error checking low confidence tags: {e}")

    return (False, 0, {})


def check_process_new(catalog_id: str, config: Dict) -> Tuple[bool, int, Dict]:
    """Check if there are new unprocessed images.

    Args:
        catalog_id: Catalog ID
        config: Configuration dict with threshold settings

    Returns:
        Tuple of (should_run, count, job_parameters)
    """
    min_count = config.get("min_images", 5)

    try:
        with get_db_context() as db:
            # Check for images without thumbnails
            result = db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM images
                    WHERE catalog_id = :catalog_id
                    AND thumbnail_path IS NULL
                """
                ),
                {"catalog_id": catalog_id},
            )
            count = result.scalar() or 0

            if count >= min_count:
                return (
                    True,
                    count,
                    {"force": False, "size": "medium"},
                )

    except Exception as e:
        logger.error(f"Error checking new images: {e}")

    return (False, 0, {})


def check_generate_thumbnails(catalog_id: str, config: Dict) -> Tuple[bool, int, Dict]:
    """Check if thumbnails need to be generated.

    Args:
        catalog_id: Catalog ID
        config: Configuration dict

    Returns:
        Tuple of (should_run, count, job_parameters)
    """
    min_count = config.get("min_images", 10)

    try:
        with get_db_context() as db:
            result = db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM images
                    WHERE catalog_id = :catalog_id
                    AND thumbnail_path IS NULL
                """
                ),
                {"catalog_id": catalog_id},
            )
            count = result.scalar() or 0

            if count >= min_count:
                return (True, count, {"force": False, "size": "medium"})

    except Exception as e:
        logger.error(f"Error checking thumbnails: {e}")

    return (False, 0, {})


def check_metadata_columns(catalog_id: str, config: Dict) -> Tuple[bool, int, Dict]:
    """Check if there are images needing metadata column extraction.

    Args:
        catalog_id: Catalog ID
        config: Configuration dict with threshold settings

    Returns:
        Tuple of (should_run, count, job_parameters)
    """
    min_count = config.get("min_images", 10)

    try:
        with get_db_context() as db:
            result = db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM images
                    WHERE catalog_id = :catalog_id
                    AND COALESCE(processing_flags->>'metadata_columns_populated', 'false') != 'true'
                """
                ),
                {"catalog_id": catalog_id},
            )
            count = result.scalar() or 0

            if count >= min_count:
                return (True, count, {})

    except Exception as e:
        logger.error(f"Error checking metadata columns: {e}")

    return (False, 0, {})


def check_score_quality(catalog_id: str, config: Dict) -> Tuple[bool, int, Dict]:
    """Check if quality scoring needs to be run.

    Args:
        catalog_id: Catalog ID
        config: Configuration dict

    Returns:
        Tuple of (should_run, count, job_parameters)
    """
    min_count = config.get("min_images", 20)

    try:
        with get_db_context() as db:
            result = db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM images
                    WHERE catalog_id = :catalog_id
                    AND quality_score IS NULL
                """
                ),
                {"catalog_id": catalog_id},
            )
            count = result.scalar() or 0

            if count >= min_count:
                return (True, count, {})

    except Exception as e:
        logger.error(f"Error checking quality scores: {e}")

    return (False, 0, {})


def check_hash_images_v2(catalog_id: str, config: Dict) -> Tuple[bool, int, Dict]:
    """Check if there are images missing multi-resolution perceptual hashes.

    Args:
        catalog_id: Catalog ID
        config: Configuration dict with threshold settings

    Returns:
        Tuple of (should_run, count, job_parameters)
    """
    min_count = config.get("min_images", 5)

    try:
        with get_db_context() as db:
            result = db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM images
                    WHERE catalog_id = :catalog_id
                    AND (dhash_16 IS NULL OR dhash_32 IS NULL)
                    AND file_type != 'video'
                """
                ),
                {"catalog_id": catalog_id},
            )
            count = result.scalar() or 0

            if count >= min_count:
                return (True, count, {})

    except Exception as e:
        logger.error(f"Error checking unhashed images: {e}")

    return (False, 0, {})


def check_detect_duplicates_v2(catalog_id: str, config: Dict) -> Tuple[bool, int, Dict]:
    """Check if there are newly hashed images not yet checked for duplicates.

    Args:
        catalog_id: Catalog ID
        config: Configuration dict with threshold settings

    Returns:
        Tuple of (should_run, count, job_parameters)
    """
    min_count = config.get("min_images", 5)

    try:
        with get_db_context() as db:
            # Images that have hashes but no duplicate_candidates entry on either side
            result = db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM images i
                    WHERE i.catalog_id = CAST(:catalog_id AS uuid)
                    AND i.dhash IS NOT NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM duplicate_candidates dc
                        WHERE dc.catalog_id = CAST(:catalog_id AS uuid)
                          AND (dc.image_id_a = i.id OR dc.image_id_b = i.id)
                    )
                """
                ),
                {"catalog_id": catalog_id},
            )
            count = result.scalar() or 0

            if count >= min_count:
                return (True, count, {"mode": "new"})

    except Exception as e:
        logger.error(f"Error checking images needing duplicate detection: {e}")

    return (False, 0, {})


# Warehouse task registry
WAREHOUSE_TASKS: Dict[str, WarehouseTask] = {
    "retag_low_confidence": WarehouseTask(
        task_type="retag_low_confidence",
        job_type="auto_tag",
        priority=30,  # PRIORITY_WAREHOUSE_HIGH
        need_assessment=check_low_confidence_tags,
        default_interval_minutes=360,  # Every 6 hours
        default_threshold={
            "confidence_threshold": 0.3,
            "min_images": 10,
        },
    ),
    "process_new": WarehouseTask(
        task_type="process_new",
        job_type="generate_thumbnails",
        priority=20,  # PRIORITY_WAREHOUSE_MEDIUM
        need_assessment=check_process_new,
        default_interval_minutes=60,  # Every hour
        default_threshold={
            "min_images": 5,
        },
    ),
    "generate_thumbnails": WarehouseTask(
        task_type="generate_thumbnails",
        job_type="generate_thumbnails",
        priority=20,  # PRIORITY_WAREHOUSE_MEDIUM
        need_assessment=check_generate_thumbnails,
        default_interval_minutes=120,  # Every 2 hours
        default_threshold={
            "min_images": 10,
        },
    ),
    "extract_metadata_columns": WarehouseTask(
        task_type="extract_metadata_columns",
        job_type="extract_metadata_columns",
        priority=25,  # Between MEDIUM and HIGH
        need_assessment=check_metadata_columns,
        default_interval_minutes=30,  # Every 30 minutes
        default_threshold={
            "min_images": 10,
        },
    ),
    "score_quality": WarehouseTask(
        task_type="score_quality",
        job_type="score_quality",
        priority=10,  # PRIORITY_WAREHOUSE_LOW
        need_assessment=check_score_quality,
        default_interval_minutes=240,  # Every 4 hours
        default_threshold={
            "min_images": 20,
        },
    ),
    "hash_images_v2": WarehouseTask(
        task_type="hash_images_v2",
        job_type="hash_images_v2",
        priority=25,  # Between MEDIUM and HIGH — runs after thumbnails
        need_assessment=check_hash_images_v2,
        default_interval_minutes=30,  # Every 30 minutes
        default_threshold={
            "min_images": 5,
        },
    ),
    "detect_duplicates_v2": WarehouseTask(
        task_type="detect_duplicates_v2",
        job_type="detect_duplicates_v2",
        priority=15,  # Just above LOW — runs after hashing
        need_assessment=check_detect_duplicates_v2,
        default_interval_minutes=60,  # Every hour
        default_threshold={
            "min_images": 5,
        },
    ),
}


def get_warehouse_task(task_type: str) -> Optional[WarehouseTask]:
    """Get warehouse task definition by type.

    Args:
        task_type: Task type identifier

    Returns:
        WarehouseTask or None if not found
    """
    return WAREHOUSE_TASKS.get(task_type)


def assess_task_need(
    task_type: str, catalog_id: str, config: Dict
) -> Tuple[bool, int, Dict]:
    """Assess if a warehouse task needs to run.

    Args:
        task_type: Task type identifier
        catalog_id: Catalog ID
        config: Task configuration

    Returns:
        Tuple of (should_run, count, job_parameters)
    """
    task = get_warehouse_task(task_type)
    if not task:
        logger.error(f"Unknown warehouse task type: {task_type}")
        return (False, 0, {})

    try:
        return task.need_assessment(catalog_id, config)
    except Exception as e:
        logger.error(f"Error assessing task {task_type}: {e}")
        return (False, 0, {})
