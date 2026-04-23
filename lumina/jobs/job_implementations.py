"""Job implementations using the new background job system."""

import logging
from pathlib import Path
from typing import Any, Callable, Dict

from ..analysis.scanner import ImageScanner
from ..db import CatalogDB as CatalogDatabase
from .background_jobs import should_stop_job, update_job_status
from .definitions import hash_v2  # noqa: F401  - registers hash_images_v2 job
from .definitions import (  # noqa: F401  - registers detect_duplicates_v2 job
    detect_duplicates_v2,
)
from .types import JobContext

logger = logging.getLogger(__name__)


def scan_analyze_job(ctx: JobContext) -> Dict[str, Any]:
    """Run catalog scan and analysis with cooperative cancellation support.

    Note: All processing is now sequential (serial) - no parallel workers.
    """
    try:
        # Check for cancellation before starting
        if should_stop_job(ctx.job_id):
            logger.info(f"Scan job {ctx.job_id} cancelled before starting")
            return {"cancelled": True}

        # Workers parameter is ignored - sequential processing only
        workers = 1

        # Convert source paths to Path objects
        source_dirs = [Path(p) for p in ctx.source_paths]

        # Open catalog database
        with CatalogDatabase(ctx.catalog_id) as catalog_db:
            # Progress callback for scanner
            def progress_callback(current: int, total: int, message: str) -> None:
                """Update job progress from scanner."""
                percent = int((current / total) * 100) if total > 0 else 0
                update_job_status(
                    ctx.job_id,
                    "PROGRESS",
                    progress={
                        "current": current,
                        "total": total,
                        "percent": percent,
                        "phase": "scanning",
                        "message": message,
                    },
                )

            # Create scanner with progress callback
            scanner = ImageScanner(
                catalog_db,
                workers=workers,
                perf_tracker=None,
                progress_callback=progress_callback,
            )

            # Update progress to indicate scanning started
            update_job_status(
                ctx.job_id,
                "PROGRESS",
                progress={"current": 0, "total": 0, "percent": 0, "phase": "scanning"},
            )

            # Check for cancellation periodically during scan
            # Note: ImageScanner doesn't support cancellation yet, but we check after
            scanner.scan_directories(source_dirs)

            # Check if cancelled after scan
            if should_stop_job(ctx.job_id):
                logger.info(f"Scan job {ctx.job_id} cancelled during execution")
                return {"cancelled": True, "partial_results": True}

            # Final result
            result = {
                "files_added": scanner.files_added,
                "files_updated": scanner.files_updated,
                "files_skipped": scanner.files_skipped,
                "files_error": scanner.files_error,
                "total_bytes": scanner.total_bytes,
                "catalog_id": ctx.catalog_id,
                # Add fields expected by frontend
                "images_found": scanner.files_added,  # For now, count all as images
                "videos_found": 0,  # TODO: Track separately
            }

            return result

    except Exception:
        logger.exception(f"Scan job {ctx.job_id} failed")
        raise


def detect_duplicates_job(ctx: JobContext) -> Dict[str, Any]:
    """Run duplicate detection using perceptual hashing.

    Args:
        ctx: Job context with catalog_id and parameters

    Returns:
        Dict with duplicate detection results
    """
    from ..analysis.duplicate_detector import DuplicateDetector

    try:
        # Get parameters
        similarity_threshold = ctx.get("similarity_threshold", 5)
        recompute_hashes = ctx.get("recompute_hashes", False)

        with CatalogDatabase(ctx.catalog_id) as catalog_db:

            def progress_callback(current: int, total: int, message: str) -> None:
                """Update job progress."""
                percent = int((current / total) * 100) if total > 0 else 0
                update_job_status(
                    ctx.job_id,
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
                ctx.job_id,
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
                "catalog_id": ctx.catalog_id,
            }

            return result

    except Exception:
        logger.exception(f"Duplicate detection job {ctx.job_id} failed")
        raise


def generate_thumbnails_job(ctx: JobContext) -> Dict[str, Any]:
    """Generate thumbnails for catalog images and update DB records."""
    from pathlib import Path

    from ..db.models import Image
    from ..shared.thumbnail_utils import THUMBNAIL_SIZES, generate_thumbnail

    try:
        force = ctx.get("force", False)
        size_name = ctx.get("size", "medium")
        size = THUMBNAIL_SIZES.get(size_name, THUMBNAIL_SIZES["medium"])
        batch_commit_size = 50

        with CatalogDatabase(ctx.catalog_id) as catalog_db:
            session = catalog_db.session
            assert session is not None

            # Query only images that need thumbnails (unless force=True)
            query = session.query(Image).filter(Image.catalog_id == ctx.catalog_id)
            if not force:
                query = query.filter(
                    (Image.thumbnail_path.is_(None)) | (Image.thumbnail_path == "")
                )
            images = query.all()

            total_images = len(images)
            thumbnails_generated = 0
            thumbnails_skipped = 0
            thumbnails_failed = 0

            # Get thumbnails directory
            thumbnails_dir = catalog_db.catalog_path / "thumbnails" / size_name
            thumbnails_dir.mkdir(parents=True, exist_ok=True)

            for i, image in enumerate(images):
                # Cooperative cancellation check
                if should_stop_job(ctx.job_id):
                    logger.info(
                        f"Thumbnail job {ctx.job_id} cancelled at {i}/{total_images}"
                    )
                    session.commit()
                    return {
                        "cancelled": True,
                        "thumbnails_generated": thumbnails_generated,
                        "thumbnails_skipped": thumbnails_skipped,
                        "thumbnails_failed": thumbnails_failed,
                        "total_images": total_images,
                        "catalog_id": ctx.catalog_id,
                    }

                # Update progress every 10 images
                if i % 10 == 0:
                    percent = int((i / total_images) * 100) if total_images > 0 else 0
                    update_job_status(
                        ctx.job_id,
                        "PROGRESS",
                        progress={
                            "current": i,
                            "total": total_images,
                            "percent": percent,
                            "phase": "generating_thumbnails",
                        },
                    )

                # Check if thumbnail already exists on disk
                thumbnail_path = thumbnails_dir / f"{image.checksum}.jpg"
                if thumbnail_path.exists() and not force:
                    # Ensure DB is up to date even for existing thumbnails
                    if not image.thumbnail_path:
                        rel_path = str(
                            thumbnail_path.relative_to(catalog_db.catalog_path)
                        )
                        image.thumbnail_path = rel_path
                        flags = dict(image.processing_flags or {})
                        flags["thumbnail_generated"] = True
                        image.processing_flags = flags
                    thumbnails_skipped += 1
                else:
                    # Generate thumbnail
                    source_path = Path(image.source_path)
                    if not source_path.exists():
                        logger.warning(f"Source file not found: {source_path}")
                        thumbnails_failed += 1
                        continue

                    success = generate_thumbnail(source_path, thumbnail_path, size=size)
                    if success:
                        rel_path = str(
                            thumbnail_path.relative_to(catalog_db.catalog_path)
                        )
                        image.thumbnail_path = rel_path
                        flags = dict(image.processing_flags or {})
                        flags["thumbnail_generated"] = True
                        image.processing_flags = flags
                        thumbnails_generated += 1
                    else:
                        thumbnails_failed += 1

                # Commit in batches
                if (i + 1) % batch_commit_size == 0:
                    session.commit()

            # Final commit
            session.commit()

            return {
                "thumbnails_generated": thumbnails_generated,
                "thumbnails_skipped": thumbnails_skipped,
                "thumbnails_failed": thumbnails_failed,
                "total_images": total_images,
                "size": size_name,
                "catalog_id": ctx.catalog_id,
            }

    except Exception:
        logger.exception(f"Thumbnail generation job {ctx.job_id} failed")
        raise


def detect_bursts_job(ctx: JobContext) -> Dict[str, Any]:
    """Detect burst photo sequences using timestamp clustering algorithm."""
    import uuid

    from sqlalchemy import text

    from ..analysis.burst_detector import BurstDetector, ImageInfo

    try:
        # Parameters
        gap_threshold = ctx.get("gap_threshold", 1.0)
        min_burst_size = ctx.get("min_burst_size", 3)

        with CatalogDatabase(ctx.catalog_id) as catalog_db:
            # Progress tracking
            def update_progress(phase: str, percent: int, message: str = "") -> None:
                update_job_status(
                    ctx.job_id,
                    "PROGRESS",
                    progress={
                        "current": percent,
                        "total": 100,
                        "percent": percent,
                        "phase": phase,
                        "message": message,
                    },
                )

            update_progress("loading", 10, "Loading images")

            # Check cancellation
            if should_stop_job(ctx.job_id):
                return {"cancelled": True}

            # Pre-flight check: ensure metadata columns are populated
            assert catalog_db.session is not None
            populated_check = catalog_db.session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM images
                    WHERE catalog_id = :catalog_id
                    AND COALESCE(processing_flags->>'metadata_columns_populated', 'false') = 'true'
                """
                ),
                {"catalog_id": ctx.catalog_id},
            )
            populated_count = populated_check.scalar() or 0
            if populated_count == 0:
                total_check = catalog_db.session.execute(
                    text("SELECT COUNT(*) FROM images WHERE catalog_id = :catalog_id"),
                    {"catalog_id": ctx.catalog_id},
                )
                total_count = total_check.scalar() or 0
                if total_count > 0:
                    raise RuntimeError(
                        f"No images have metadata columns populated ({total_count} images exist). "
                        "Run the 'extract_metadata_columns' job first."
                    )

            # Load images with metadata
            result = catalog_db.session.execute(
                text(
                    """
                    SELECT id, capture_time, camera_make, camera_model,
                           quality_score, source_path, latitude, longitude,
                           COALESCE(geohash_6, '') as geohash,
                           focal_length, aperture, iso, dhash
                    FROM images
                    WHERE catalog_id = :catalog_id
                    AND capture_time IS NOT NULL
                    ORDER BY capture_time
                """
                ),
                {"catalog_id": ctx.catalog_id},
            )

            images = [
                ImageInfo(
                    image_id=str(row[0]),
                    timestamp=row[1],
                    camera_make=row[2],
                    camera_model=row[3],
                    quality_score=row[4] or 0.0,
                    source_path=row[5],
                    latitude=row[6],
                    longitude=row[7],
                    geohash=row[8],
                    focal_length=row[9],
                    aperture=row[10],
                    iso=row[11],
                    dhash=row[12],
                )
                for row in result.fetchall()
            ]

            update_progress("detecting", 40, f"Analyzing {len(images)} images")

            # Check cancellation
            if should_stop_job(ctx.job_id):
                return {"cancelled": True}

            # Detect bursts
            detector = BurstDetector(
                gap_threshold_seconds=gap_threshold,
                min_burst_size=min_burst_size,
            )
            bursts = detector.detect_bursts(images)

            update_progress("saving", 70, f"Saving {len(bursts)} bursts")

            # Clear old bursts
            assert catalog_db.session is not None
            catalog_db.session.execute(
                text("DELETE FROM bursts WHERE catalog_id = :catalog_id"),
                {"catalog_id": ctx.catalog_id},
            )

            # Save bursts
            total_images_in_bursts = 0
            for burst in bursts:
                burst_id = str(uuid.uuid4())

                # Insert burst record
                assert catalog_db.session is not None
                catalog_db.session.execute(
                    text(
                        """
                        INSERT INTO bursts (
                            id, catalog_id, image_count, start_time, end_time,
                            duration_seconds, camera_make, camera_model,
                            best_image_id, selection_method, created_at
                        ) VALUES (
                            :id, :catalog_id, :image_count, :start_time, :end_time,
                            :duration, :make, :model, :best_image, :method, NOW()
                        )
                    """
                    ),
                    {
                        "id": burst_id,
                        "catalog_id": ctx.catalog_id,
                        "image_count": burst.image_count,
                        "start_time": burst.start_time,
                        "end_time": burst.end_time,
                        "duration": burst.duration_seconds,
                        "make": burst.camera_make,
                        "model": burst.camera_model,
                        "best_image": burst.best_image_id,
                        "method": burst.selection_method,
                    },
                )

                # Update images with burst_id
                for idx, img in enumerate(burst.images):
                    assert catalog_db.session is not None
                    catalog_db.session.execute(
                        text(
                            """
                            UPDATE images
                            SET burst_id = :burst_id, burst_sequence = :sequence
                            WHERE id = :image_id
                        """
                        ),
                        {
                            "burst_id": burst_id,
                            "sequence": idx,
                            "image_id": img.image_id,
                        },
                    )

                total_images_in_bursts += burst.image_count

            assert catalog_db.session is not None
            catalog_db.session.commit()
            update_progress("complete", 100, "Done")

            return {
                "bursts_detected": len(bursts),
                "images_in_bursts": total_images_in_bursts,
                "catalog_id": ctx.catalog_id,
            }

    except Exception:
        logger.exception(f"Burst detection job {ctx.job_id} failed")
        raise


def auto_tag_job(ctx: JobContext) -> Dict[str, Any]:
    """Auto-tag images using AI backends with GPU batch processing."""
    import json
    import os
    from pathlib import Path
    from typing import Optional, Union

    from sqlalchemy import text

    from ..analysis.image_tagger import (
        CombinedTagger,
        ImageTagger,
        check_backends_available,
    )
    from .tag_storage import store_image_tags

    try:
        # Parameters
        backend = ctx.get("backend", "openclip")
        model = ctx.get("model", None)
        threshold = ctx.get("threshold", 0.25)
        max_tags = ctx.get("max_tags", 10)
        tag_mode = ctx.get("tag_mode", "untagged_only")
        batch_size = ctx.get("batch_size", 32)

        # Backend availability check
        backends_status = check_backends_available()

        if backend == "openclip" and not backends_status.get("openclip"):
            raise RuntimeError(
                "OpenCLIP backend not available. Install with: pip install open-clip-torch"
            )
        if backend == "ollama" and not backends_status.get("ollama"):
            raise RuntimeError(
                "Ollama backend not available. Ensure Ollama is running with a vision model."
            )
        if backend == "combined":
            if not backends_status.get("openclip"):
                raise RuntimeError(
                    "Combined backend requires OpenCLIP. Install with: pip install open-clip-torch"
                )
            if not backends_status.get("ollama"):
                raise RuntimeError(
                    "Combined backend requires Ollama. Ensure Ollama is running with a vision model."
                )

        with CatalogDatabase(ctx.catalog_id) as catalog_db:
            # Progress update helper
            update_job_status(
                ctx.job_id,
                "PROGRESS",
                progress={
                    "current": 0,
                    "total": 100,
                    "percent": 0,
                    "phase": "init",
                    "backend": backend,
                },
            )

            # Check cancellation
            if should_stop_job(ctx.job_id):
                return {"cancelled": True}

            # Get images based on tag_mode
            if tag_mode == "untagged_only":
                # Only images without any tags
                assert catalog_db.session is not None
                result = catalog_db.session.execute(
                    text(
                        """
                        SELECT i.id, i.source_path FROM images i
                        WHERE i.catalog_id = :catalog_id
                        AND i.file_type = 'image'
                        AND NOT EXISTS (
                            SELECT 1 FROM image_tags it WHERE it.image_id = i.id
                        )
                    """
                    ),
                    {"catalog_id": ctx.catalog_id},
                )
            else:
                # All images - for retagging
                assert catalog_db.session is not None
                result = catalog_db.session.execute(
                    text(
                        """
                        SELECT i.id, i.source_path FROM images i
                        WHERE i.catalog_id = :catalog_id
                        AND i.file_type = 'image'
                    """
                    ),
                    {"catalog_id": ctx.catalog_id},
                )

            images_to_tag = result.fetchall()
            total_images = len(images_to_tag)

            if total_images == 0:
                # Check if all images are already tagged
                assert catalog_db.session is not None
                result = catalog_db.session.execute(
                    text("SELECT COUNT(*) FROM images WHERE catalog_id = :catalog_id"),
                    {"catalog_id": ctx.catalog_id},
                )
                total_in_catalog = result.scalar() or 0

                if total_in_catalog > 0:
                    return {
                        "images_tagged": 0,
                        "images_failed": 0,
                        "total_images": total_in_catalog,
                        "message": f"All {total_in_catalog} images already tagged",
                        "catalog_id": ctx.catalog_id,
                    }
                else:
                    return {
                        "images_tagged": 0,
                        "images_failed": 0,
                        "total_images": 0,
                        "message": "No images in catalog",
                        "catalog_id": ctx.catalog_id,
                    }

            # GPU detection
            device = "cpu"
            try:
                import torch

                if torch.cuda.is_available():
                    device = "cuda"
                    logger.info("GPU acceleration enabled")
            except ImportError:
                pass

            # Initialize tagger
            tagger: Union[CombinedTagger, ImageTagger]
            if backend == "combined":
                tagger = CombinedTagger(
                    openclip_model=model or "ViT-B-32",
                    ollama_model="llava",
                    device=device,
                    ollama_host=os.environ.get("OLLAMA_HOST"),
                )
            else:
                tagger = ImageTagger(
                    backend=backend,
                    model=model,
                    device=device if backend == "openclip" else None,
                )

            # Check for checkpoint to resume
            def get_checkpoint() -> Optional[int]:
                """Get the last checkpoint offset."""
                assert catalog_db.session is not None
                result = catalog_db.session.execute(
                    text(
                        """
                        SELECT value FROM config
                        WHERE catalog_id = :catalog_id AND key = :key
                    """
                    ),
                    {
                        "catalog_id": ctx.catalog_id,
                        "key": f"auto_tag_checkpoint_{ctx.job_id}",
                    },
                )
                row = result.fetchone()
                if row:
                    return row[0] if isinstance(row[0], int) else json.loads(row[0])
                return None

            def save_checkpoint(offset: int) -> None:
                """Save checkpoint for resuming."""
                assert catalog_db.session is not None
                catalog_db.session.execute(
                    text(
                        """
                        INSERT INTO config (catalog_id, key, value, updated_at)
                        VALUES (:catalog_id, :key, :value, NOW())
                        ON CONFLICT (catalog_id, key) DO UPDATE SET
                            value = EXCLUDED.value,
                            updated_at = EXCLUDED.updated_at
                    """
                    ),
                    {
                        "catalog_id": ctx.catalog_id,
                        "key": f"auto_tag_checkpoint_{ctx.job_id}",
                        "value": json.dumps(offset),
                    },
                )
                assert catalog_db.session is not None
                catalog_db.session.commit()

            start_offset = get_checkpoint() or 0
            if start_offset > 0:
                logger.info(f"Resuming from checkpoint: {start_offset}/{total_images}")

            tagged_count = 0
            failed_count = 0

            # Process images
            if backend in ("openclip", "combined"):
                # Batch processing for OpenCLIP
                for batch_start in range(start_offset, total_images, batch_size):
                    if should_stop_job(ctx.job_id):
                        return {
                            "cancelled": True,
                            "images_tagged": tagged_count,
                            "images_failed": failed_count,
                            "total_images": total_images,
                            "catalog_id": ctx.catalog_id,
                        }

                    batch_end = min(batch_start + batch_size, total_images)
                    batch = images_to_tag[batch_start:batch_end]
                    batch_paths: list[Union[str, Path]] = [
                        Path(row[1]) for row in batch
                    ]
                    batch_ids = [row[0] for row in batch]

                    # Update progress
                    percent = (
                        int((batch_start / total_images) * 100)
                        if total_images > 0
                        else 0
                    )
                    update_job_status(
                        ctx.job_id,
                        "PROGRESS",
                        progress={
                            "current": batch_start,
                            "total": total_images,
                            "percent": percent,
                            "phase": "tagging",
                            "backend": backend,
                        },
                    )

                    try:
                        # Tag batch
                        if backend == "combined" and isinstance(tagger, CombinedTagger):
                            # Combined backend with progress callback
                            # Capture loop variable to avoid B023 closure issue
                            _batch_start = batch_start

                            def progress_cb(
                                current: int,
                                total: int,
                                phase: str,
                                _bs: int = _batch_start,
                            ) -> None:
                                update_job_status(
                                    ctx.job_id,
                                    "PROGRESS",
                                    progress={
                                        "current": _bs + current,
                                        "total": total_images,
                                        "percent": int(
                                            ((_bs + current) / total_images) * 100
                                        ),
                                        "phase": "tagging",
                                        "sub_phase": phase,
                                    },
                                )

                            results = tagger.tag_batch(
                                batch_paths,
                                threshold=threshold,
                                max_tags=max_tags,
                                progress_callback=progress_cb,
                            )
                        else:
                            results = tagger.tag_batch(
                                batch_paths,
                                threshold=threshold,
                                max_tags=max_tags,
                            )

                        # Store tags and embeddings
                        for img_id, img_path in zip(batch_ids, batch_paths):
                            # img_path is always Path, but annotated as Union for batch_paths
                            tags = results.get(
                                (
                                    img_path
                                    if isinstance(img_path, Path)
                                    else Path(img_path)
                                ),
                                [],
                            )
                            if tags:
                                stored = store_image_tags(
                                    catalog_db,
                                    ctx.catalog_id,
                                    str(img_id),
                                    tags,
                                    backend,
                                )
                                if stored > 0:
                                    tagged_count += 1

                            # Save CLIP embedding for semantic search
                            if backend in ("openclip", "combined") and hasattr(
                                tagger, "get_embedding"
                            ):
                                try:
                                    embedding = tagger.get_embedding(img_path)
                                    assert catalog_db.session is not None
                                    catalog_db.session.execute(
                                        text(
                                            """
                                            UPDATE images
                                            SET clip_embedding = :embedding
                                            WHERE id = :image_id
                                        """
                                        ),
                                        {
                                            "image_id": str(img_id),
                                            "embedding": embedding,
                                        },
                                    )
                                except Exception as e:
                                    logger.warning(
                                        f"Failed to save embedding for {img_id}: {e}"
                                    )

                        assert catalog_db.session is not None
                        catalog_db.session.commit()

                        # Save checkpoint after each batch
                        save_checkpoint(batch_end)

                    except Exception as batch_e:
                        logger.warning(f"Batch tagging failed: {batch_e}")
                        failed_count += len(batch)
                        # Still save checkpoint so we don't reprocess failed batch
                        save_checkpoint(batch_end)

            else:  # ollama
                # Sequential processing for Ollama
                for i, (img_id, source_path) in enumerate(images_to_tag):
                    if i < start_offset:
                        continue

                    if should_stop_job(ctx.job_id):
                        return {
                            "cancelled": True,
                            "images_tagged": tagged_count,
                            "images_failed": failed_count,
                            "total_images": total_images,
                            "catalog_id": ctx.catalog_id,
                        }

                    # Update progress
                    percent = int((i / total_images) * 100) if total_images > 0 else 0
                    update_job_status(
                        ctx.job_id,
                        "PROGRESS",
                        progress={
                            "current": i,
                            "total": total_images,
                            "percent": percent,
                            "phase": "tagging",
                            "current_file": Path(source_path).name,
                        },
                    )

                    try:
                        tags = tagger.tag_image(
                            source_path,
                            threshold=threshold,
                            max_tags=max_tags,
                        )

                        if tags:
                            stored = store_image_tags(
                                catalog_db, ctx.catalog_id, str(img_id), tags, "ollama"
                            )
                            if stored > 0:
                                tagged_count += 1

                        # Commit and checkpoint every 10 images
                        if (i + 1) % 10 == 0:
                            assert catalog_db.session is not None
                            catalog_db.session.commit()
                            save_checkpoint(i + 1)

                    except Exception as img_e:
                        logger.warning(f"Failed to tag {source_path}: {img_e}")
                        failed_count += 1

                # Final commit
                assert catalog_db.session is not None
                catalog_db.session.commit()

            # Cleanup
            if hasattr(tagger, "cleanup"):
                tagger.cleanup()

            # Final progress
            update_job_status(
                ctx.job_id,
                "PROGRESS",
                progress={
                    "current": total_images,
                    "total": total_images,
                    "percent": 100,
                    "phase": "complete",
                },
            )

            return {
                "images_tagged": tagged_count,
                "images_failed": failed_count,
                "total_images": total_images,
                "backend": backend,
                "catalog_id": ctx.catalog_id,
            }

    except Exception:
        logger.exception(f"Auto-tagging job {ctx.job_id} failed")
        raise


def extract_metadata_columns_job(ctx: JobContext) -> Dict[str, Any]:
    """Extract metadata from JSONB columns into queryable typed columns.

    Reads dates and metadata JSONB, populates dedicated columns (capture_time,
    camera_make, etc.), and sets processing_flags.metadata_columns_populated.
    """
    import json
    from datetime import datetime as dt

    from sqlalchemy import text

    try:
        force = ctx.get("force", False)
        batch_size = 100

        with CatalogDatabase(ctx.catalog_id) as catalog_db:
            assert catalog_db.session is not None

            # Count images needing processing
            if force:
                count_result = catalog_db.session.execute(
                    text("SELECT COUNT(*) FROM images WHERE catalog_id = :catalog_id"),
                    {"catalog_id": ctx.catalog_id},
                )
            else:
                count_result = catalog_db.session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM images
                        WHERE catalog_id = :catalog_id
                        AND COALESCE(processing_flags->>'metadata_columns_populated', 'false') != 'true'
                    """
                    ),
                    {"catalog_id": ctx.catalog_id},
                )
            total_count = count_result.scalar() or 0

            if total_count == 0:
                return {
                    "images_processed": 0,
                    "message": "All images already have metadata columns populated",
                    "catalog_id": ctx.catalog_id,
                }

            update_job_status(
                ctx.job_id,
                "PROGRESS",
                progress={
                    "current": 0,
                    "total": total_count,
                    "percent": 0,
                    "phase": "extracting_metadata",
                },
            )

            # Known column mappings from metadata JSONB
            metadata_column_map = {
                "camera_make": "camera_make",
                "camera_model": "camera_model",
                "lens_model": "lens_model",
                "width": "width",
                "height": "height",
                "iso": "iso",
                "aperture": "aperture",
                "shutter_speed": "shutter_speed",
                "focal_length": "focal_length",
                "gps_latitude": "latitude",
                "gps_longitude": "longitude",
                "gps_altitude": "gps_altitude",
                "orientation": "orientation",
                "format": "format",
                "perceptual_hash_dhash": "dhash",
                "perceptual_hash_ahash": "ahash",
                "perceptual_hash_whash": "whash",
            }

            # Keys that are expected in metadata JSONB but not mapped to columns
            known_non_column_keys = {
                "exif",
                "resolution",
                "size_bytes",
                "geohash",
                "flash",
                "artist",
                "copyright",
                "merged_from",
            }

            unknown_fields_seen = set()
            images_processed = 0
            offset = 0

            while True:
                if should_stop_job(ctx.job_id):
                    logger.info(
                        f"Extract metadata job {ctx.job_id} cancelled at {images_processed}/{total_count}"
                    )
                    return {
                        "cancelled": True,
                        "images_processed": images_processed,
                        "total_images": total_count,
                        "catalog_id": ctx.catalog_id,
                    }

                # Fetch a batch
                if force:
                    batch_result = catalog_db.session.execute(
                        text(
                            """
                            SELECT id, dates, metadata, processing_flags,
                                   geohash_4, geohash_6, geohash_8
                            FROM images
                            WHERE catalog_id = :catalog_id
                            ORDER BY id
                            LIMIT :limit OFFSET :offset
                        """
                        ),
                        {
                            "catalog_id": ctx.catalog_id,
                            "limit": batch_size,
                            "offset": offset,
                        },
                    )
                else:
                    batch_result = catalog_db.session.execute(
                        text(
                            """
                            SELECT id, dates, metadata, processing_flags,
                                   geohash_4, geohash_6, geohash_8
                            FROM images
                            WHERE catalog_id = :catalog_id
                            AND COALESCE(processing_flags->>'metadata_columns_populated', 'false') != 'true'
                            ORDER BY id
                            LIMIT :limit
                        """
                        ),
                        {"catalog_id": ctx.catalog_id, "limit": batch_size},
                    )

                rows = batch_result.fetchall()
                if not rows:
                    break

                for row in rows:
                    image_id = row[0]
                    dates = row[1] or {}
                    metadata = row[2] or {}
                    flags = dict(row[3] or {})
                    existing_geohash_4 = row[4]
                    existing_geohash_6 = row[5]
                    existing_geohash_8 = row[6]

                    # Extract capture_time from dates JSONB
                    capture_time = None
                    selected_date = dates.get("selected_date")
                    if selected_date:
                        if isinstance(selected_date, str):
                            try:
                                capture_time = dt.fromisoformat(
                                    selected_date.replace("Z", "+00:00")
                                )
                            except (ValueError, TypeError):
                                pass
                        elif isinstance(selected_date, dt):
                            capture_time = selected_date

                    capture_time_source = dates.get("selected_source")
                    date_confidence = dates.get("confidence")

                    # Extract columns from metadata JSONB
                    column_values = {}
                    for json_key, col_name in metadata_column_map.items():
                        val = metadata.get(json_key)
                        if val is not None:
                            column_values[col_name] = val

                    # Collect unmapped metadata keys into metadata_extra
                    all_known_keys = (
                        set(metadata_column_map.keys()) | known_non_column_keys
                    )
                    extra = {}
                    for key, val in metadata.items():
                        if key not in all_known_keys and val is not None:
                            extra[key] = val
                            unknown_fields_seen.add(key)

                    # Populate geohash columns if GPS present and geohash available
                    geohash_updates = {}
                    geohash_val = metadata.get("geohash")
                    if geohash_val and isinstance(geohash_val, str):
                        if not existing_geohash_4 and len(geohash_val) >= 4:
                            geohash_updates["geohash_4"] = geohash_val[:4]
                        if not existing_geohash_6 and len(geohash_val) >= 6:
                            geohash_updates["geohash_6"] = geohash_val[:6]
                        if not existing_geohash_8 and len(geohash_val) >= 8:
                            geohash_updates["geohash_8"] = geohash_val[:8]

                    # Mark as populated
                    flags["metadata_columns_populated"] = True

                    # Build UPDATE SET clause dynamically
                    set_parts = [
                        "capture_time = :capture_time",
                        "capture_time_source = :capture_time_source",
                        "date_confidence = :date_confidence",
                        "processing_flags = :flags::jsonb",
                    ]
                    params = {
                        "image_id": image_id,
                        "capture_time": capture_time,
                        "capture_time_source": capture_time_source,
                        "date_confidence": date_confidence,
                        "flags": json.dumps(flags),
                    }

                    for col_name, val in column_values.items():
                        set_parts.append(f"{col_name} = :{col_name}")
                        params[col_name] = val

                    if extra:
                        set_parts.append("metadata_extra = :metadata_extra::jsonb")
                        params["metadata_extra"] = json.dumps(extra)

                    for gh_col, gh_val in geohash_updates.items():
                        set_parts.append(f"{gh_col} = :{gh_col}")
                        params[gh_col] = gh_val

                    catalog_db.session.execute(
                        text(
                            f"UPDATE images SET {', '.join(set_parts)} WHERE id = :image_id"
                        ),
                        params,
                    )

                    images_processed += 1

                # Commit batch
                catalog_db.session.commit()
                offset += batch_size

                # Update progress
                percent = (
                    int((images_processed / total_count) * 100)
                    if total_count > 0
                    else 0
                )
                update_job_status(
                    ctx.job_id,
                    "PROGRESS",
                    progress={
                        "current": images_processed,
                        "total": total_count,
                        "percent": percent,
                        "phase": "extracting_metadata",
                    },
                )

            # Log unknown fields for future migration planning
            if unknown_fields_seen:
                logger.info(
                    f"Metadata fields without dedicated columns: {sorted(unknown_fields_seen)}. "
                    "Consider adding columns in a future migration."
                )

            return {
                "images_processed": images_processed,
                "total_images": total_count,
                "unknown_metadata_fields": (
                    sorted(unknown_fields_seen) if unknown_fields_seen else []
                ),
                "catalog_id": ctx.catalog_id,
            }

    except Exception:
        logger.exception(f"Extract metadata columns job {ctx.job_id} failed")
        raise


def test_job(ctx: JobContext) -> Dict[str, Any]:
    """Test job that simulates work with progress tracking and cancellation support.

    This job does nothing but sleep and report progress, useful for testing:
    - Job execution (RUN)
    - Progress tracking (TRACK)
    - Cooperative cancellation (KILL)
    """
    import time

    duration = ctx.get("duration_seconds", 30)
    update_interval = ctx.get("update_interval_seconds", 1)

    logger.info(f"Test job {ctx.job_id} starting (duration: {duration}s)")

    start_time = time.time()
    iterations = int(duration / update_interval)

    for i in range(iterations):
        # Check if cancelled
        if should_stop_job(ctx.job_id):
            logger.info(
                f"Test job {ctx.job_id} cancelled at iteration {i}/{iterations}"
            )
            return {
                "status": "cancelled",
                "iterations_completed": i,
                "total_iterations": iterations,
                "elapsed_seconds": int(time.time() - start_time),
            }

        # Report progress
        percent = int((i / iterations) * 100)
        update_job_status(
            ctx.job_id,
            "PROGRESS",
            progress={
                "current": i,
                "total": iterations,
                "percent": percent,
                "phase": "processing",
                "message": f"Iteration {i+1}/{iterations}",
            },
        )

        logger.info(f"Test job {ctx.job_id}: {percent}% ({i+1}/{iterations})")

        # Simulate work
        time.sleep(update_interval)

    elapsed = int(time.time() - start_time)
    logger.info(f"Test job {ctx.job_id} completed in {elapsed}s")

    return {
        "status": "completed",
        "iterations_completed": iterations,
        "total_iterations": iterations,
        "elapsed_seconds": elapsed,
        "catalog_id": ctx.catalog_id,
    }


def _run_framework_job(ctx: "JobContext", job_name: str) -> Dict[str, Any]:
    """Run a framework-registered job (ParallelJob) via the global REGISTRY.

    Args:
        ctx: The job context (provides job_id and catalog_id)
        job_name: Name of the registered ParallelJob to execute

    Returns:
        Result dict from the job's finalize function (or executor summary)
    """
    from .framework import REGISTRY, JobExecutor

    job = REGISTRY.get(job_name)
    if job is None:
        raise ValueError(f"No framework job registered under name '{job_name}'")

    executor = JobExecutor(job)
    return executor.run(ctx.job_id, ctx.catalog_id, **ctx.parameters)


def organize_job(ctx: JobContext) -> Dict[str, Any]:
    """Reorganize catalog files into the catalog's organized_directory.

    Parameters (via ctx.parameters):
        operation: "copy" (default) or "move"
        dry_run: bool — if True, plan only, no filesystem changes (default False)
        scope: "new" (default), "iffy", "unresolved", or "all"

    Returns:
        summary: count breakdown
        exceptions: list of items needing attention (iffy, unresolved, collision, error)
        dry_run: whether this was a preview-only run
    """
    from pathlib import Path

    from ..db import get_db_context
    from ..db.models import Catalog, Image
    from ..jobs.definitions.organize import _plan_organization
    from ..shared.media_utils import compute_checksum

    operation = ctx.get("operation", "copy")
    dry_run = ctx.get("dry_run", False)
    scope = ctx.get("scope", "new")

    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={"current": 0, "total": 100, "percent": 0, "phase": "loading"},
    )

    # Load catalog and validate organized_directory
    with get_db_context() as db:
        catalog = db.query(Catalog).filter(Catalog.id == ctx.catalog_id).first()
        if not catalog:
            raise ValueError(f"Catalog {ctx.catalog_id} not found")
        if not catalog.organized_directory:
            raise ValueError(
                "Catalog has no organized_directory configured. "
                "Set it in catalog settings before organizing."
            )
        output_dir = Path(catalog.organized_directory)

    # Query images based on scope
    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={"current": 5, "total": 100, "percent": 5, "phase": "discovering"},
    )

    with get_db_context() as db:
        query = db.query(Image).filter(Image.catalog_id == ctx.catalog_id)
        images = query.all()

    # Build organization plan
    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={"current": 10, "total": 100, "percent": 10, "phase": "planning"},
    )

    plan = _plan_organization(images, output_dir, scope)

    if dry_run:
        return {
            "dry_run": True,
            "summary": plan["summary"],
            "exceptions": plan["exceptions"],
        }

    # Execute file operations
    operations = plan["operations"]
    total_ops = len(operations)
    organized = 0
    errors = []

    import shutil

    for i, op in enumerate(operations):
        if should_stop_job(ctx.job_id):
            break

        percent = 10 + int((i / max(total_ops, 1)) * 85)
        update_job_status(
            ctx.job_id,
            "PROGRESS",
            progress={
                "current": i,
                "total": total_ops,
                "percent": percent,
                "phase": "organizing",
                "message": f"Organizing {i + 1}/{total_ops}",
            },
        )

        source = Path(op["source_path"])
        dest = Path(op["dest_path"])

        if not source.exists():
            errors.append(
                {"image_id": op["image_id"], "error": f"Source not found: {source}"}
            )
            continue

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)

            if operation == "copy":
                shutil.copy2(str(source), str(dest))
            else:
                shutil.move(str(source), str(dest))

            # Checksum verification
            dest_checksum = compute_checksum(dest)
            with get_db_context() as db:
                image = db.query(Image).filter(Image.id == op["image_id"]).first()
                if image:
                    if image.checksum != dest_checksum:
                        dest.unlink(missing_ok=True)
                        raise ValueError(f"Checksum mismatch after {operation}")
                    image.organized_path = str(dest)
                    flags = dict(image.processing_flags or {})
                    flags["organized"] = True
                    flags["organization_confidence"] = op["tier"]
                    image.processing_flags = flags
                    db.commit()

            organized += 1

        except Exception as e:
            logger.error(f"Error organizing {source}: {e}")
            errors.append({"image_id": op["image_id"], "error": str(e)})

    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={"current": 100, "total": 100, "percent": 100, "phase": "finalizing"},
    )

    return {
        "dry_run": False,
        "summary": {
            **plan["summary"],
            "organized": organized,
            "errors": len(errors),
        },
        "exceptions": plan["exceptions"],
        "error_details": errors,
    }


def auto_resolve_duplicates_job(ctx: Any) -> Dict[str, Any]:
    """Auto-resolve duplicate candidates using deterministic quality rules.

    For each unreviewed candidate with hamming=0 (pixel-identical content):
      1. Higher resolution wins
      2. Larger file wins (better quality/less compression) if same dims
      3. Better filename wins if files are otherwise equal
      4. format_variant layer: higher format tier wins (RAW > TIFF > HEIC > JPEG)

    Writes proper duplicate_decisions + suppression_pairs + archives the loser,
    identical to a manual user decision.

    Parameters:
        layers: list of layers to process (default: ["near_duplicate", "format_variant"])
        dry_run: if True, count decisions without writing them (default: False)
        batch_size: commit frequency (default: 500)
    """
    import os
    import re
    import uuid as uuid_mod

    from sqlalchemy import text as sa_text

    from ..analysis.dedup.archive import archive_image
    from ..db.connection import get_db_context

    layers = ctx.get("layers", ["near_duplicate", "format_variant"])
    dry_run = ctx.get("dry_run", False)
    batch_size = ctx.get("batch_size", 500)

    FORMAT_TIER = {
        "RAW": 100,
        "TIFF": 80,
        "HEIC": 60,
        "HEIF": 60,
        "JPEG": 50,
        "JPG": 50,
        "PNG": 45,
        "GIF": 10,
    }

    def filename_score(path: str) -> int:
        stem = os.path.splitext(os.path.basename(path))[0]
        score = 0
        if re.search(r"20\d{2}[_\-]?\d{4}", stem):
            score += 3
        if re.search(r"\d{8}", stem):
            score += 2
        if len(stem) > 12:
            score += 1
        if re.match(r"^(IMG|DSC|DSCF|MVI|MOV|VID|P\d+|image)[-_]?\d+$", stem, re.I):
            score -= 2
        if re.match(r"^\d{4,8}$", stem):
            score -= 1
        return score

    def pick_primary(row) -> tuple[str, str]:
        """Return (primary_id, reason) — primary is the one to KEEP."""
        pid_a, pid_b = str(row.image_id_a), str(row.image_id_b)

        # For format_variant: prefer higher format tier
        if row.layer == "format_variant":
            tier_a = FORMAT_TIER.get((row.format_a or "").upper(), 40)
            tier_b = FORMAT_TIER.get((row.format_b or "").upper(), 40)
            if tier_a != tier_b:
                return (pid_a if tier_a > tier_b else pid_b, "format_tier")

        # Higher resolution wins
        pixels_a = (row.width_a or 0) * (row.height_a or 0)
        pixels_b = (row.width_b or 0) * (row.height_b or 0)
        if pixels_a != pixels_b:
            return (pid_a if pixels_a > pixels_b else pid_b, "resolution")

        # Larger file wins (better compression = more data retained)
        size_a, size_b = row.size_a or 0, row.size_b or 0
        size_ratio = abs(size_a - size_b) / max(size_a, size_b, 1)
        if size_ratio > 0.05:  # >5% difference is meaningful
            return (pid_a if size_a > size_b else pid_b, "file_size")

        # Better filename wins
        fn_a = filename_score(row.path_a or "")
        fn_b = filename_score(row.path_b or "")
        if fn_a != fn_b:
            return (pid_a if fn_a > fn_b else pid_b, "filename")

        # Tiebreak: larger file
        return (pid_a if size_a >= size_b else pid_b, "tiebreak_size")

    # Load all unreviewed candidates for eligible layers
    with get_db_context() as db:
        placeholders = ", ".join(f"'{layer}'" for layer in layers)
        candidates = db.execute(
            sa_text(
                f"""
            SELECT
                dc.id, dc.catalog_id, dc.image_id_a, dc.image_id_b,
                dc.layer, dc.confidence, dc.detection_meta,
                ia.source_path AS path_a, ia.size_bytes AS size_a,
                ia.width AS width_a, ia.height AS height_a, ia.format AS format_a,
                ib.source_path AS path_b, ib.size_bytes AS size_b,
                ib.width AS width_b, ib.height AS height_b, ib.format AS format_b
            FROM duplicate_candidates dc
            JOIN images ia ON ia.id = dc.image_id_a
            JOIN images ib ON ib.id = dc.image_id_b
            WHERE dc.catalog_id = CAST(:cid AS uuid)
              AND dc.reviewed_at IS NULL
              AND dc.layer IN ({placeholders})
              AND (dc.detection_meta->>'hamming')::int = 0
        """
            ),
            {"cid": str(ctx.catalog_id)},
        ).fetchall()

    total = len(candidates)
    resolved = 0
    skipped = 0
    reasons: Dict[str, int] = {}

    for i, row in enumerate(candidates):
        if should_stop_job(ctx.job_id):
            break

        try:
            primary_id, reason = pick_primary(row)
            reasons[reason] = reasons.get(reason, 0) + 1

            if not dry_run:
                decision_id = str(uuid_mod.uuid4())
                with get_db_context() as db:
                    # 1. Write decision
                    db.execute(
                        sa_text(
                            """
                        INSERT INTO duplicate_decisions
                            (id, candidate_id, decision, primary_id, notes, decided_at)
                        VALUES (CAST(:id AS uuid), CAST(:cid AS uuid),
                                'confirmed_duplicate', :primary_id,
                                :notes, NOW())
                    """
                        ),
                        {
                            "id": decision_id,
                            "cid": str(row.id),
                            "primary_id": primary_id,
                            "notes": f"auto-resolved: {reason}",
                        },
                    )

                    # 2. Mark reviewed
                    db.execute(
                        sa_text(
                            "UPDATE duplicate_candidates SET reviewed_at = NOW() WHERE id = CAST(:id AS uuid)"
                        ),
                        {"id": str(row.id)},
                    )

                    # 3. Suppress pair
                    id_a = min(str(row.image_id_a), str(row.image_id_b))
                    id_b = max(str(row.image_id_a), str(row.image_id_b))
                    db.execute(
                        sa_text(
                            """
                        INSERT INTO suppression_pairs (id_a, id_b, decision, created_at)
                        VALUES (:a, :b, 'confirmed_duplicate', NOW())
                        ON CONFLICT (id_a, id_b) DO NOTHING
                    """
                        ),
                        {"a": id_a, "b": id_b},
                    )

                    # 4. Archive the loser
                    archive_id = (
                        str(row.image_id_b)
                        if str(row.image_id_b) != primary_id
                        else str(row.image_id_a)
                    )
                    archive_image(
                        image_id=archive_id,
                        decision_id=decision_id,
                        archive_reason=row.layer,
                        primary_image_id=primary_id,
                        session=db,
                    )
                    db.commit()

            resolved += 1
        except Exception as e:
            logger.warning(f"Failed to resolve candidate {row.id}: {e}")
            skipped += 1

        if (i + 1) % batch_size == 0 or i == total - 1:
            pct = int((i + 1) / total * 100)
            update_job_status(
                ctx.job_id,
                "PROGRESS",
                progress={
                    "current": i + 1,
                    "total": total,
                    "percent": pct,
                    "message": f"{'[dry run] ' if dry_run else ''}Resolved {resolved}/{total}",
                },
            )

    return {
        "resolved": resolved,
        "skipped": skipped,
        "total_eligible": total,
        "dry_run": dry_run,
        "reasons": reasons,
    }


def classify_images_job(ctx: Any) -> Dict[str, Any]:
    """Classify images by content type using fast heuristics + optional Ollama VLM.

    Tier 1 (heuristics, runs on all images, very fast):
      - PIL validation: marks unreadable files as 'invalid'
      - Tiny images (<= 64px) as 'invalid'
      - Exact device screen dimensions as 'screenshot'
      - Extreme aspect ratios as 'screenshot'
      - Animated GIFs as 'other'

    Tier 2 (Ollama VLM, optional, only for images heuristics can't resolve):
      - Only runs when use_vlm=True

    Parameters:
        model: Ollama model (default: qwen3-vl)
        use_vlm: run VLM on images heuristics label 'unknown' (default: False)
        reclassify: re-run on already-classified images (default: False)
        batch_size: DB commit frequency (default: 500)
    """
    from sqlalchemy import text as sa_text

    from ..analysis.image_classifier import ImageClassifier, heuristic_classify

    model = ctx.get("model", "qwen3-vl")
    use_vlm = ctx.get("use_vlm", False)
    reclassify = ctx.get("reclassify", False)
    batch_size = ctx.get("batch_size", 500)

    # Resolve the catalog's data root for thumbnail path resolution
    catalog_root = Path(f"/app/catalogs/{ctx.catalog_id}")

    classifier = ImageClassifier(model=model) if use_vlm else None

    with CatalogDatabase(ctx.catalog_id) as catalog_db:
        assert catalog_db.session is not None
        where_clause = "" if reclassify else "AND content_class IS NULL"
        rows = catalog_db.session.execute(
            sa_text(
                f"""
                SELECT id, source_path, thumbnail_path
                FROM images
                WHERE catalog_id = CAST(:cid AS uuid)
                  AND file_type = 'image'
                  {where_clause}
                ORDER BY id
            """
            ),
            {"cid": str(ctx.catalog_id)},
        ).fetchall()

    total = len(rows)
    if total == 0:
        return {"classified": 0, "total": 0, "skipped": 0, "by_class": {}}

    classified = 0
    failed = 0
    by_class: Dict[str, int] = {}
    pending_updates: list = []

    def flush(force: bool = False):
        nonlocal classified
        if not pending_updates or (not force and len(pending_updates) < batch_size):
            return
        with CatalogDatabase(ctx.catalog_id) as db2:
            assert db2.session is not None
            for img_id, label in pending_updates:
                db2.session.execute(
                    sa_text("UPDATE images SET content_class = :cls WHERE id = :id"),
                    {"cls": label, "id": str(img_id)},
                )
            db2.session.commit()
        classified += len(pending_updates)
        pending_updates.clear()

    for i, row in enumerate(rows):
        img_id, source_path, thumbnail_path = row

        if should_stop_job(ctx.job_id):
            break

        # Resolve paths: thumbnails are relative to catalog_root
        path_to_use = None
        if thumbnail_path:
            p = catalog_root / thumbnail_path
            if p.exists():
                path_to_use = p
        if path_to_use is None:
            p = Path(source_path)
            if p.exists():
                path_to_use = p

        if path_to_use is None:
            failed += 1
        else:
            try:
                label, _ = heuristic_classify(path_to_use)
                if label == "unknown" and use_vlm and classifier:
                    label = classifier.classify_with_vlm(path_to_use)
                elif label == "unknown":
                    label = "other"  # heuristics undecided, no VLM → leave as other
                by_class[label] = by_class.get(label, 0) + 1
                pending_updates.append((img_id, label))
                flush()
            except Exception as e:
                logger.warning(f"Classification failed for {img_id}: {e}")
                failed += 1

        if (i + 1) % batch_size == 0 or i == total - 1:
            flush(force=True)
            pct = int((i + 1) / total * 100)
            update_job_status(
                ctx.job_id,
                "PROGRESS",
                progress={
                    "current": i + 1,
                    "total": total,
                    "percent": pct,
                    "message": f"Classified {classified + len(pending_updates)}/{total}",
                },
            )

    flush(force=True)

    return {
        "classified": classified,
        "failed": failed,
        "total": total,
        "use_vlm": use_vlm,
        "by_class": by_class,
    }


# Job registry
def detect_events_job(ctx: Any) -> Dict[str, Any]:
    """Detect photographic events using time-space clustering.

    Groups GPS-tagged images that are:
    - Within max_radius_km of each other (default 0.402 km = 0.25 miles)
    - Separated by no more than max_gap_hours between consecutive shots (default 2h)

    Filters to events with >= min_images and >= min_duration_hours.
    Score = images_per_hour (density) — higher means more event-like.
    Clears previous event detection results before writing new ones.
    """
    import uuid as uuid_mod
    from datetime import datetime
    from math import atan2, cos, radians, sin, sqrt

    from sqlalchemy import text

    from ..db.connection import get_db_context

    MIN_IMAGES: int = ctx.get("min_images", 10)
    MIN_DURATION_H: float = ctx.get("min_duration_hours", 1.0)
    MAX_RADIUS_KM: float = ctx.get("max_radius_km", 0.402)  # 0.25 miles
    MAX_GAP_H: float = ctx.get("max_gap_hours", 2.0)

    def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371.0
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = (
            sin(dlat / 2) ** 2
            + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
        )
        return R * 2 * atan2(sqrt(a), sqrt(1.0 - a))

    def parse_dt(s: str) -> datetime:
        # Handle both with/without timezone and various formats
        s = s.strip()
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(
                    s[
                        : len(
                            fmt.replace("%f", "ffffff")
                            .replace("%Y", "2000")
                            .replace("%m", "01")
                            .replace("%d", "01")
                            .replace("%H", "00")
                            .replace("%M", "00")
                            .replace("%S", "00")
                        )
                    ],
                    fmt,
                )
            except ValueError:
                continue
        raise ValueError(f"Cannot parse date: {s}")

    catalog_id = str(ctx.catalog_id)

    # --- Load GPS images sorted by date ---
    with get_db_context() as db:
        rows = db.execute(
            text(
                """
                SELECT id, latitude, longitude,
                    COALESCE(
                        dates->>'selected_date',
                        dates->>'exif_date',
                        dates->>'filename_date',
                        dates->>'filesystem_date'
                    ) AS photo_date
                FROM images
                WHERE catalog_id = CAST(:cid AS uuid)
                  AND latitude IS NOT NULL AND longitude IS NOT NULL
                  AND status_id = 'active'
                ORDER BY photo_date ASC NULLS LAST
            """
            ),
            {"cid": catalog_id},
        ).fetchall()

    # Filter out nulls and parse dates
    images = []
    for r in rows:
        if not r.photo_date:
            continue
        try:
            dt = parse_dt(r.photo_date)
            images.append((r.id, float(r.latitude), float(r.longitude), dt))
        except (ValueError, TypeError):
            continue

    if not images:
        return {"events_detected": 0, "images_clustered": 0}

    logger.info(
        f"Event detection: {len(images)} GPS images to cluster for catalog {catalog_id}"
    )

    # --- Build clusters: consecutive images connected if gap < MAX_GAP_H AND dist < MAX_RADIUS_KM ---
    # Use Union-Find on sorted sequence: connect i → i+1 if within constraints
    parent = list(range(len(images)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(1, len(images)):
        _, lat_a, lon_a, dt_a = images[i - 1]
        _, lat_b, lon_b, dt_b = images[i]
        gap_h = (dt_b - dt_a).total_seconds() / 3600.0
        if gap_h < 0 or gap_h > MAX_GAP_H:
            continue
        dist_km = haversine(lat_a, lon_a, lat_b, lon_b)
        if dist_km <= MAX_RADIUS_KM:
            union(i - 1, i)

    # Group by cluster root
    from collections import defaultdict

    cluster_map: Dict[int, list] = defaultdict(list)
    for i, img in enumerate(images):
        cluster_map[find(i)].append(img)

    # --- Score and filter clusters ---
    events_to_write = []
    for members in cluster_map.values():
        if len(members) < MIN_IMAGES:
            continue

        members.sort(key=lambda x: x[3])  # sort by date within cluster
        start_dt = members[0][3]
        end_dt = members[-1][3]
        duration_h = (end_dt - start_dt).total_seconds() / 3600.0

        if duration_h < MIN_DURATION_H:
            continue

        lats = [m[1] for m in members]
        lons = [m[2] for m in members]
        center_lat = sum(lats) / len(lats)
        center_lon = sum(lons) / len(lons)
        radius_km = max(haversine(center_lat, center_lon, m[1], m[2]) for m in members)

        # Score: images per hour — higher is denser/more event-like
        # Bonus for tight radius, penalty for very long events
        density = len(members) / max(duration_h, 0.25)
        spatial_bonus = 1.0 / (1.0 + radius_km)
        score = density * spatial_bonus

        events_to_write.append(
            {
                "id": str(uuid_mod.uuid4()),
                "catalog_id": catalog_id,
                "start_time": start_dt,
                "end_time": end_dt,
                "duration_minutes": int(duration_h * 60),
                "image_count": len(members),
                "center_lat": center_lat,
                "center_lon": center_lon,
                "radius_km": radius_km,
                "score": score,
                "images": [m[0] for m in members],
            }
        )

    events_to_write.sort(key=lambda e: e["score"], reverse=True)
    logger.info(f"Event detection: {len(events_to_write)} events found before writing")

    # --- Write to DB (clear old results first) ---
    with get_db_context() as db:
        db.execute(
            text("DELETE FROM events WHERE catalog_id = CAST(:cid AS uuid)"),
            {"cid": catalog_id},
        )

        for ev in events_to_write:
            db.execute(
                text(
                    """
                    INSERT INTO events
                        (id, catalog_id, start_time, end_time, duration_minutes,
                         image_count, center_lat, center_lon, radius_km, score)
                    VALUES
                        (CAST(:id AS uuid), CAST(:cid AS uuid), :start, :end, :dur,
                         :cnt, :lat, :lon, :rad, :score)
                """
                ),
                {
                    "id": ev["id"],
                    "cid": catalog_id,
                    "start": ev["start_time"],
                    "end": ev["end_time"],
                    "dur": ev["duration_minutes"],
                    "cnt": ev["image_count"],
                    "lat": ev["center_lat"],
                    "lon": ev["center_lon"],
                    "rad": ev["radius_km"],
                    "score": ev["score"],
                },
            )
            if ev["images"]:
                db.execute(
                    text(
                        """
                        INSERT INTO event_images (event_id, image_id)
                        VALUES (CAST(:eid AS uuid), :img_id)
                        ON CONFLICT DO NOTHING
                    """
                    ),
                    [{"eid": ev["id"], "img_id": img_id} for img_id in ev["images"]],
                )

        db.commit()

    total_clustered = sum(e["image_count"] for e in events_to_write)
    return {
        "events_detected": len(events_to_write),
        "images_clustered": total_clustered,
        "gps_images_processed": len(images),
    }


JOB_FUNCTIONS: Dict[str, Callable[..., Any]] = {
    "scan": scan_analyze_job,
    "analyze": scan_analyze_job,
    "detect_duplicates": detect_duplicates_job,
    "generate_thumbnails": generate_thumbnails_job,
    "detect_bursts": detect_bursts_job,
    "auto_tag": auto_tag_job,
    "extract_metadata_columns": extract_metadata_columns_job,
    "test": test_job,  # Test job for verification
    "hash_images_v2": lambda ctx: _run_framework_job(ctx, "hash_images_v2"),
    "detect_duplicates_v2": lambda ctx: _run_framework_job(ctx, "detect_duplicates_v2"),
    "organize": organize_job,
    "classify_images": classify_images_job,
    "auto_resolve_duplicates": auto_resolve_duplicates_job,
    "detect_events": detect_events_job,
}
