"""Atomic archive operation: copies image row to archived_images with provenance."""

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def archive_image(
    image_id: str,
    decision_id: str,
    archive_reason: str,
    primary_image_id: str,
    session: Session,
) -> None:
    """Copy an image row to archived_images and set its status to 'archived'.

    This operation is atomic within the caller's transaction.
    The source file is never touched — only the catalog record is moved.

    Args:
        image_id: The image to archive (will be set to status 'archived')
        decision_id: UUID of the duplicate_decisions row that authorised this
        archive_reason: The detection layer name (exact, reimport, etc.)
        primary_image_id: The image that survives (kept in catalog)
        session: Active SQLAlchemy session (caller commits)
    """
    session.execute(
        text(
            """
            INSERT INTO archived_images (
                id, catalog_id, source_path, file_type, checksum, size_bytes,
                dates, metadata, thumbnail_path,
                dhash, ahash, whash, dhash_16, dhash_32,
                quality_score, capture_time, camera_make, camera_model,
                width, height, format, latitude, longitude,
                processing_flags, created_at,
                archived_at, archive_reason, decision_id,
                primary_image_id, original_catalog_id, restoration_path
            )
            SELECT
                id, catalog_id, source_path, file_type, checksum, size_bytes,
                dates, metadata, thumbnail_path,
                dhash, ahash, whash, dhash_16, dhash_32,
                quality_score, capture_time, camera_make, camera_model,
                width, height, format, latitude, longitude,
                processing_flags, created_at,
                NOW(), :reason, CAST(:decision_id AS uuid),
                :primary_id, catalog_id, source_path
            FROM images WHERE id = :image_id
            ON CONFLICT (id) DO NOTHING
        """
        ),
        {
            "image_id": image_id,
            "reason": archive_reason,
            "decision_id": decision_id,
            "primary_id": primary_image_id,
        },
    )
    session.execute(
        text("UPDATE images SET status_id = 'archived' WHERE id = :id"),
        {"id": image_id},
    )
    logger.info(
        f"Archived image {image_id} (reason={archive_reason}, kept={primary_image_id})"
    )


def restore_image(archived_id: str, session: Session) -> None:
    """Restore an archived image back to active status.

    Removes from archived_images and sets status back to 'active'.
    Does NOT delete the duplicate_decisions record — the audit trail is preserved.
    """
    session.execute(
        text("UPDATE images SET status_id = 'active' WHERE id = :id"),
        {"id": archived_id},
    )
    session.execute(
        text("DELETE FROM archived_images WHERE id = :id"),
        {"id": archived_id},
    )
    logger.info(f"Restored archived image {archived_id}")
