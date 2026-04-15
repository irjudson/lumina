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
        gap_threshold = ctx.get("gap_threshold", 2.0)
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


# Job registry
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
}
