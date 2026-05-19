"""Score quality job definition.

Batch-processes all images in a catalog that are missing a quality_score.
Reads images in batches of 500, computes the quality score using the
calculate_quality_score function, stores round(score.overall) as
quality_score INTEGER, and sets processing_flags['quality_scored'] = True.
"""

import logging
from typing import Any, Dict

from ..background_jobs import should_stop_job, update_job_status
from ..types import JobContext

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def score_quality_job(ctx: JobContext) -> Dict[str, Any]:
    """Score quality for all unscored images in a catalog.

    Reads images in batches of 500.  For each image:
      - Builds ImageMetadata from DB columns and the metadata JSONB field
      - Determines FileType (IMAGE or VIDEO)
      - Calls calculate_quality_score(metadata, file_type)
      - Stores round(score.overall) as quality_score
      - Sets processing_flags['quality_scored'] = True

    Respects should_stop_job() for cooperative cancellation.

    Returns:
        Dict with "scored" and "skipped" counts.
    """
    from sqlalchemy import text

    from ...analysis.quality_scorer import calculate_quality_score
    from ...core.types import FileType, ImageMetadata
    from ...db import get_db_context

    scored = 0
    skipped = 0

    # Count total unscored images for progress reporting
    with get_db_context() as db:
        total_row = db.execute(
            text(
                "SELECT COUNT(*) FROM images "
                "WHERE catalog_id = CAST(:cid AS uuid) AND quality_score IS NULL"
            ),
            {"cid": ctx.catalog_id},
        ).fetchone()
        total_unscored = total_row[0] if total_row else 0

    if total_unscored == 0:
        update_job_status(
            ctx.job_id,
            "PROGRESS",
            progress={"current": 0, "total": 0, "percent": 100, "phase": "complete"},
        )
        return {"scored": 0, "skipped": 0}

    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={
            "current": 0,
            "total": total_unscored,
            "percent": 0,
            "phase": "scoring",
        },
    )

    last_id = ""
    while True:
        if should_stop_job(ctx.job_id):
            logger.info(
                f"score_quality job {ctx.job_id} cancelled after id {last_id!r}"
            )
            return {"scored": scored, "skipped": skipped, "cancelled": True}

        with get_db_context() as db:
            rows = db.execute(
                text(
                    """
                    SELECT
                        id,
                        file_type,
                        format,
                        width,
                        height,
                        size_bytes,
                        camera_make,
                        camera_model,
                        lens_model,
                        focal_length,
                        aperture,
                        shutter_speed,
                        iso,
                        latitude,
                        longitude,
                        metadata
                    FROM images
                    WHERE catalog_id = CAST(:cid AS uuid)
                      AND quality_score IS NULL
                      AND id > :last_id
                    ORDER BY id
                    LIMIT :limit
                    """
                ),
                {"cid": ctx.catalog_id, "limit": BATCH_SIZE, "last_id": last_id},
            ).fetchall()

            if not rows:
                break

            for row in rows:
                (
                    image_id,
                    file_type_str,
                    fmt,
                    width,
                    height,
                    size_bytes,
                    camera_make,
                    camera_model,
                    lens_model,
                    focal_length,
                    aperture,
                    shutter_speed,
                    iso,
                    latitude,
                    longitude,
                    metadata_json,
                ) = row

                # Pull extra fields from metadata JSONB if not in columns
                meta_dict = metadata_json or {}

                # Prefer dedicated columns; fall back to JSONB
                resolved_focal_length = focal_length
                if resolved_focal_length is None:
                    try:
                        v = meta_dict.get("focal_length")
                        resolved_focal_length = float(v) if v is not None else None
                    except (TypeError, ValueError):
                        resolved_focal_length = None

                resolved_aperture = aperture
                if resolved_aperture is None:
                    try:
                        v = meta_dict.get("aperture")
                        resolved_aperture = float(v) if v is not None else None
                    except (TypeError, ValueError):
                        resolved_aperture = None

                resolved_shutter_speed = shutter_speed
                if resolved_shutter_speed is None:
                    v = meta_dict.get("shutter_speed")
                    resolved_shutter_speed = str(v) if v is not None else None

                resolved_iso = iso
                if resolved_iso is None:
                    try:
                        v = meta_dict.get("iso")
                        resolved_iso = int(v) if v is not None else None
                    except (TypeError, ValueError):
                        resolved_iso = None

                resolved_lat = latitude
                if resolved_lat is None:
                    try:
                        v = meta_dict.get("gps_latitude")
                        resolved_lat = float(v) if v is not None else None
                    except (TypeError, ValueError):
                        resolved_lat = None

                resolved_lon = longitude
                if resolved_lon is None:
                    try:
                        v = meta_dict.get("gps_longitude")
                        resolved_lon = float(v) if v is not None else None
                    except (TypeError, ValueError):
                        resolved_lon = None

                image_metadata = ImageMetadata(
                    format=fmt,
                    width=width,
                    height=height,
                    size_bytes=size_bytes,
                    camera_make=camera_make,
                    camera_model=camera_model,
                    lens_model=lens_model,
                    focal_length=resolved_focal_length,
                    aperture=resolved_aperture,
                    shutter_speed=resolved_shutter_speed,
                    iso=resolved_iso,
                    gps_latitude=resolved_lat,
                    gps_longitude=resolved_lon,
                )

                file_type = (
                    FileType.VIDEO if file_type_str == "video" else FileType.IMAGE
                )

                try:
                    score = calculate_quality_score(image_metadata, file_type)
                    quality_int = round(score.overall)

                    db.execute(
                        text(
                            """
                            UPDATE images
                            SET quality_score = :qs,
                                processing_flags = processing_flags || '{"quality_scored": true}'::jsonb
                            WHERE id = :img_id
                            """
                        ),
                        {"qs": quality_int, "img_id": image_id},
                    )
                    scored += 1
                except Exception as e:
                    logger.warning(f"Failed to score image {image_id}: {e}")
                    skipped += 1

            db.commit()
            # Advance cursor to the last processed id
            last_id = rows[-1][0]

        # Report progress after each batch
        processed = scored + skipped
        percent = int((processed / total_unscored) * 100) if total_unscored > 0 else 100
        update_job_status(
            ctx.job_id,
            "PROGRESS",
            progress={
                "current": processed,
                "total": total_unscored,
                "percent": min(percent, 99),
                "phase": "scoring",
            },
        )

    logger.info(
        f"score_quality job {ctx.job_id} complete: "
        f"scored={scored}, skipped={skipped}"
    )
    return {"scored": scored, "skipped": skipped}
