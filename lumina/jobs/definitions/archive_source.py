"""Source file archiving job.

After images are organized (organized_path IS NOT NULL), this job verifies
the organized copy matches the original checksum, then optionally deletes
the source file to reclaim disk space.

Parameters (ctx.parameters):
    dry_run (bool, default True):  preview mode — report what would change
    scope (str, default "all"):
        "all"       — all organized active images not yet source-archived
        "resolved"  — only images with organization_confidence = resolved
"""

import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def archive_source_job(ctx) -> Dict[str, Any]:
    from sqlalchemy import text

    from ...db import get_db_context
    from ...jobs.coordinator import should_stop_job, update_job_status

    dry_run: bool = ctx.get("dry_run", True)
    scope: str = ctx.get("scope", "all")
    catalog_id: str = ctx.catalog_id

    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={"percent": 0, "message": "Loading candidates"},
    )

    confidence_filter = ""
    if scope == "resolved":
        confidence_filter = (
            "AND processing_flags->>'organization_confidence' = 'resolved'"
        )

    with get_db_context() as db:
        rows = db.execute(
            text(
                f"""
                SELECT id, source_path, organized_path, checksum
                FROM images
                WHERE catalog_id = CAST(:cid AS uuid)
                  AND organized_path IS NOT NULL
                  AND status_id NOT IN ('rejected', 'archived')
                  AND COALESCE((processing_flags->>'source_archived')::boolean, false) = false
                  AND source_path IS NOT NULL
                  {confidence_filter}
                ORDER BY id
                """
            ),
            {"cid": catalog_id},
        ).fetchall()

    total = len(rows)
    if total == 0:
        return {
            "dry_run": dry_run,
            "candidates": 0,
            "verified": 0,
            "archived": 0,
            "skipped_missing_source": 0,
            "skipped_missing_organized": 0,
            "checksum_mismatches": 0,
            "bytes_freed": 0,
        }

    verified = 0
    archived = 0
    skipped_missing_source = 0
    skipped_missing_organized = 0
    checksum_mismatches = 0
    bytes_freed = 0

    for idx, row in enumerate(rows):
        if should_stop_job(ctx.job_id):
            break

        if idx % 100 == 0:
            pct = 5 + int((idx / total) * 90)
            update_job_status(
                ctx.job_id,
                "PROGRESS",
                progress={
                    "percent": pct,
                    "message": f"Verifying {idx:,}/{total:,}",
                },
            )

        src = Path(row.source_path)
        org = Path(row.organized_path)

        if not src.exists():
            skipped_missing_source += 1
            continue

        if not org.exists():
            skipped_missing_organized += 1
            continue

        # Verify organized copy matches stored checksum (which was computed on source)
        if row.checksum:
            try:
                from ...shared.media_utils import compute_checksum

                org_checksum = compute_checksum(str(org))
                if org_checksum != row.checksum:
                    checksum_mismatches += 1
                    logger.warning(
                        "Checksum mismatch for %s: source=%s organized=%s",
                        row.id,
                        row.checksum,
                        org_checksum,
                    )
                    continue
            except Exception as e:
                logger.warning("Could not verify checksum for %s: %s", row.id, e)
                continue

        verified += 1
        file_size = src.stat().st_size if src.exists() else 0

        if not dry_run:
            try:
                src.unlink()
                bytes_freed += file_size
                archived += 1

                with get_db_context() as db:
                    db.execute(
                        text(
                            """
                            UPDATE images
                            SET processing_flags = processing_flags || '{"source_archived": true}'::jsonb
                            WHERE id = :img_id
                            """
                        ),
                        {"img_id": row.id},
                    )
                    db.commit()
            except Exception as e:
                logger.error("Failed to archive source %s: %s", src, e)
        else:
            bytes_freed += file_size
            archived += 1

    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={"percent": 100, "message": "Done"},
    )

    return {
        "dry_run": dry_run,
        "candidates": total,
        "verified": verified,
        "archived": archived,
        "skipped_missing_source": skipped_missing_source,
        "skipped_missing_organized": skipped_missing_organized,
        "checksum_mismatches": checksum_mismatches,
        "bytes_freed": bytes_freed,
    }
