"""
Image scanner using SQLAlchemy ORM (PostgreSQL).

This replaces the SQLite-based scanner with a proper ORM-based implementation.
"""

import hashlib
import logging
import os
import time
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from sqlalchemy.orm import Session

from lumina.shared import compute_checksum, get_file_type
from lumina.shared.thumbnail_utils import get_thumbnail_path

from ..core.performance_stats import PerformanceTracker
from ..core.types import CatalogPhase, FileType, ImageRecord, ImageStatus
from ..db.models import Config, Image, Statistics
from .metadata import MetadataExtractor

logger = logging.getLogger(__name__)


def _populate_metadata_columns(image: "Image", dates_obj, metadata_obj) -> None:
    """Populate queryable metadata columns on an Image ORM object.

    Args:
        image: Image ORM object to update
        dates_obj: DateInfo pydantic model (or None)
        metadata_obj: ImageMetadata pydantic model (or None)
    """
    if dates_obj:
        if dates_obj.selected_date:
            image.capture_time = dates_obj.selected_date
        if dates_obj.selected_source:
            image.capture_time_source = dates_obj.selected_source
        if dates_obj.confidence:
            image.date_confidence = dates_obj.confidence

    if metadata_obj:
        if metadata_obj.camera_make:
            image.camera_make = metadata_obj.camera_make
        if metadata_obj.camera_model:
            image.camera_model = metadata_obj.camera_model
        if metadata_obj.lens_model:
            image.lens_model = metadata_obj.lens_model
        if metadata_obj.width is not None:
            image.width = metadata_obj.width
        if metadata_obj.height is not None:
            image.height = metadata_obj.height
        if metadata_obj.iso is not None:
            image.iso = metadata_obj.iso
        if metadata_obj.aperture is not None:
            image.aperture = metadata_obj.aperture
        if metadata_obj.shutter_speed:
            image.shutter_speed = metadata_obj.shutter_speed
        if metadata_obj.focal_length is not None:
            image.focal_length = metadata_obj.focal_length
        if metadata_obj.gps_latitude is not None:
            image.latitude = metadata_obj.gps_latitude
        if metadata_obj.gps_longitude is not None:
            image.longitude = metadata_obj.gps_longitude
        if metadata_obj.gps_altitude is not None:
            image.gps_altitude = metadata_obj.gps_altitude
        if metadata_obj.orientation is not None:
            image.orientation = metadata_obj.orientation
        if metadata_obj.format:
            image.format = metadata_obj.format

        # Populate geohash columns from metadata geohash
        if metadata_obj.geohash and isinstance(metadata_obj.geohash, str):
            gh = metadata_obj.geohash
            if not image.geohash_4 and len(gh) >= 4:
                image.geohash_4 = gh[:4]
            if not image.geohash_6 and len(gh) >= 6:
                image.geohash_6 = gh[:6]
            if not image.geohash_8 and len(gh) >= 8:
                image.geohash_8 = gh[:8]


def _process_file_sequential(
    file_path: Path, extractor: MetadataExtractor
) -> Optional[Tuple[ImageRecord, int]]:
    """
    Process a single file sequentially.

    Args:
        file_path: Path to the file to process
        extractor: MetadataExtractor instance (reused across files)

    Returns:
        Tuple of (ImageRecord, file_size) if successful, None if skipped/failed
    """
    try:
        # Determine file type
        file_type_str = get_file_type(file_path)
        if file_type_str == "image":
            file_type = FileType.IMAGE
        elif file_type_str == "video":
            file_type = FileType.VIDEO
        else:
            return None  # Skip unknown files

        # Compute checksum
        checksum = compute_checksum(file_path)
        if not checksum:
            logger.warning(f"Failed to compute checksum for {file_path}")
            return None

        # Extract metadata
        metadata = extractor.extract_metadata(file_path, file_type)
        dates = extractor.extract_dates(file_path, metadata)

        # Create image record
        image = ImageRecord(
            id=checksum,  # Temporary - will be updated by scanner
            source_path=file_path,
            file_type=file_type,
            checksum=checksum,
            dates=dates,
            metadata=metadata,
            status=ImageStatus.ANALYZING,
        )

        return (image, metadata.size_bytes or 0)

    except Exception as e:
        logger.error(f"Error processing {file_path}: {e}")
        return None


class ImageScannerORM:
    """
    Scans directories for images and videos using SQLAlchemy ORM.

    This replaces the raw SQL implementation with proper ORM usage.
    """

    def __init__(
        self,
        session: Session,
        catalog_id: str,
        catalog_path: Path,
        workers: int = 1,  # Ignored - kept for API compatibility
        perf_tracker: Optional[PerformanceTracker] = None,
        progress_callback: Optional[callable] = None,
    ):
        """
        Initialize the scanner with SQLAlchemy session.

        Args:
            session: SQLAlchemy session
            catalog_id: Catalog UUID
            catalog_path: Path to catalog directory (for thumbnails)
            workers: Number of parallel workers (IGNORED - sequential processing only)
            perf_tracker: Optional performance tracker
            progress_callback: Optional callback(current, total, message) for progress updates
        """
        self.session = session
        self.catalog_id = catalog_id
        self.catalog_path = (
            Path(catalog_path) if not isinstance(catalog_path, Path) else catalog_path
        )
        self.workers = 1  # Always 1 - sequential processing only
        self.perf_tracker = perf_tracker
        self.progress_callback = progress_callback

        # Track scanning statistics
        self.files_added = 0
        self.files_updated = 0  # Updated incomplete records
        self.files_skipped = 0
        self.files_error = 0
        self.total_bytes = 0
        self.start_time = None
        self.end_time = None

        # Track total files for progress reporting
        self._total_files = 0
        self._processed_files = 0
        self._files_discovered = 0
        self._last_progress_time = None

    def scan_directories(self, directories: List[Path]) -> None:
        """
        Scan directories for images and videos using incremental discovery.
        All processing is now sequential (serial) - no parallelism.

        Args:
            directories: List of directories to scan
        """
        logger.info(f"Scanning {len(directories)} directories (sequential mode)")
        print(f"DEBUG: scan_directories called with {directories}", flush=True)
        self.start_time = time.time()

        # Update catalog phase in config
        print("DEBUG: About to call _update_config", flush=True)
        self._update_config("phase", CatalogPhase.ANALYZING.value)
        print("DEBUG: _update_config completed", flush=True)

        # Track file collection
        ctx = (
            self.perf_tracker.track_operation(
                "scan_directories", items=len(directories)
            )
            if self.perf_tracker
            else nullcontext()
        )

        with ctx:
            # Process files incrementally as they're discovered
            batch_size = 100
            current_batch = []
            files_discovered = 0

            logger.info(
                "Starting incremental file discovery and processing (sequential)..."
            )

            for directory in directories:
                logger.info(f"Scanning directory: {directory}")

                # Discover and process files incrementally
                for file_path in self._discover_files_incrementally(Path(directory)):
                    current_batch.append(file_path)
                    files_discovered += 1
                    self._files_discovered = files_discovered

                    # Update progress (discovery phase - every 50 files or every 2 seconds)
                    now = time.time()
                    should_update = files_discovered % 50 == 0 or (
                        self._last_progress_time and now - self._last_progress_time >= 2
                    )

                    if self.progress_callback and should_update:
                        elapsed = now - self.start_time
                        rate = files_discovered / elapsed if elapsed > 0 else 0
                        # Use 0 as total during discovery (unknown total)
                        # Current = files discovered so far
                        self.progress_callback(
                            files_discovered,
                            0,  # Total unknown during discovery
                            f"Discovering files... {files_discovered} found ({rate:.1f} files/s)",
                        )
                        self._last_progress_time = now

                    # Process batch when it reaches batch_size
                    if len(current_batch) >= batch_size:
                        logger.info(
                            f"Processing batch of {len(current_batch)} files "
                            f"({files_discovered} discovered so far)"
                        )
                        self._process_files(current_batch)
                        current_batch = []

                        # Update progress after processing batch
                        if self.progress_callback:
                            elapsed = time.time() - self.start_time
                            rate = self._processed_files / elapsed if elapsed > 0 else 0
                            self.progress_callback(
                                self._processed_files,
                                files_discovered,
                                f"Processing... {self._processed_files}/{files_discovered} ({rate:.1f} files/s)",
                            )
                            self._last_progress_time = time.time()

            # Process remaining files
            if current_batch:
                logger.info(f"Processing final batch of {len(current_batch)} files")
                self._process_files(current_batch)

            # Final progress update
            if self.progress_callback:
                elapsed = time.time() - self.start_time
                rate = self._processed_files / elapsed if elapsed > 0 else 0
                self.progress_callback(
                    self._processed_files,
                    files_discovered,
                    f"Complete: {self._processed_files} files ({rate:.1f} files/s)",
                )

        self.end_time = time.time()
        self._update_statistics()

        # Log summary
        logger.info(
            f"Scan complete: {self.files_added} added, "
            f"{self.files_skipped} skipped, {self.files_error} errors"
        )

    def _discover_files_incrementally(self, directory: Path) -> Iterator[Path]:
        """
        Discover files incrementally without blocking.

        Args:
            directory: Directory to scan

        Yields:
            Paths to discovered image/video files
        """
        if not directory.exists():
            logger.warning(f"Directory does not exist: {directory}")
            return

        # Walk directory tree
        for root, dirs, files in os.walk(directory):
            root_path = Path(root)

            # Skip Synology metadata directories
            dirs[:] = [d for d in dirs if d != "@eaDir"]

            for file in files:
                # Skip hidden files
                if file.startswith("."):
                    continue

                file_path = root_path / file

                # Quick check based on extension
                ext = file_path.suffix.lower()
                if ext in {
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".gif",
                    ".bmp",
                    ".tiff",
                    ".webp",
                    ".heic",
                    ".raw",
                    ".mp4",
                    ".avi",
                    ".mov",
                    ".wmv",
                    ".mkv",
                }:
                    yield file_path

    def _process_files(self, file_paths: List[Path]) -> None:
        """
        Process a batch of files sequentially (serial processing only).

        Args:
            file_paths: List of file paths to process
        """
        # Create a single metadata extractor to reuse across all files in this batch
        with MetadataExtractor() as extractor:
            # Process files sequentially - no parallelism
            results = [_process_file_sequential(f, extractor) for f in file_paths]

        # Count processed files for progress tracking
        self._processed_files += len(file_paths)

        # Track checksums in this batch to avoid duplicates within the batch
        batch_checksums = set()

        # Add results to database
        for result, file_path in zip(results, file_paths):
            if result is None:
                self.files_error += 1
                continue

            image_record, file_size = result
            self.total_bytes += file_size

            # Check if image already exists by checksum (in database or in this batch)
            if image_record.checksum in batch_checksums:
                logger.debug(f"Skipping duplicate in batch: {file_path}")
                self.files_skipped += 1
                continue

            existing = (
                self.session.query(Image)
                .filter_by(catalog_id=self.catalog_id, checksum=image_record.checksum)
                .first()
            )

            if existing:
                # Check if the existing record needs updating (incomplete scan)
                flags = existing.processing_flags or {}
                needs_update = not flags.get(
                    "metadata_extracted", False
                ) or not flags.get("dates_extracted", False)

                if needs_update:
                    # Update the existing record with new metadata
                    self._update_existing_image(existing, image_record, file_path)
                    self.files_updated += 1
                    logger.debug(f"Updated incomplete record: {file_path}")
                else:
                    logger.debug(f"Skipping complete record: {file_path}")
                    self.files_skipped += 1
                continue

            # Track this checksum for the current batch
            batch_checksums.add(image_record.checksum)

            # Thumbnails are generated by the background generate_thumbnails job
            thumbnail_path = None

            # Generate unique ID per catalog (catalog_id + checksum hash)
            unique_id = hashlib.sha256(
                f"{self.catalog_id}:{image_record.checksum}".encode()
            ).hexdigest()

            # Build processing flags based on what was successfully extracted
            processing_flags = {
                "metadata_extracted": bool(
                    image_record.metadata and image_record.metadata.exif
                ),
                "dates_extracted": bool(
                    image_record.dates
                    and image_record.dates.selected_date
                    and image_record.dates.confidence >= 70
                ),
                "thumbnail_generated": bool(thumbnail_path),
                "hashes_computed": False,  # Set by duplicate detection task
                "quality_scored": False,  # Set by quality scoring task
                "embedding_generated": False,  # Set by CLIP embedding task
                "tags_applied": False,  # Set by auto-tagging task
            }
            # Mark as ready for analysis if metadata and dates are extracted
            processing_flags["ready_for_analysis"] = (
                processing_flags["metadata_extracted"]
                and processing_flags["dates_extracted"]
            )

            # Map workflow status to database status
            # Most workflow states (pending, analyzing, etc.) -> active
            # Only user actions change status to rejected/archived/flagged
            status_str = image_record.status.value
            status_mapping = {
                "complete": "archived",
                "rejected": "rejected",
                "archived": "archived",
                "flagged": "flagged",
            }
            db_status = status_mapping.get(status_str, "active")

            # Create ORM object
            image = Image(
                id=unique_id,
                catalog_id=self.catalog_id,
                source_path=str(image_record.source_path),
                file_type=image_record.file_type.value,
                checksum=image_record.checksum,
                size_bytes=(
                    image_record.metadata.size_bytes if image_record.metadata else None
                ),
                dates=(
                    image_record.dates.model_dump(mode="json")
                    if image_record.dates
                    else {}
                ),
                metadata_json=(
                    image_record.metadata.model_dump(mode="json")
                    if image_record.metadata
                    else {}
                ),
                thumbnail_path=thumbnail_path,
                status_id=db_status,
                processing_flags=processing_flags,
            )

            # Populate queryable metadata columns inline
            _populate_metadata_columns(image, image_record.dates, image_record.metadata)
            processing_flags["metadata_columns_populated"] = True
            image.processing_flags = processing_flags

            self.session.add(image)
            self.files_added += 1
            logger.debug(f"Added: {file_path}")

        # Commit batch
        try:
            self.session.commit()
        except Exception as e:
            logger.error(f"Failed to commit batch: {e}")
            self.session.rollback()
            self.files_error += len(file_paths)

    def _update_existing_image(
        self, existing: Image, image_record: ImageRecord, file_path: Path
    ) -> None:
        """
        Update an existing image record with new metadata.

        This is called when an image exists but has incomplete processing flags.
        Only updates fields that are missing or incomplete.

        Args:
            existing: The existing Image ORM object
            image_record: The newly extracted ImageRecord
            file_path: Path to the source file
        """
        flags = existing.processing_flags or {}

        # Only update metadata if not already extracted
        if not flags.get("metadata_extracted", False) and image_record.metadata:
            existing.metadata_json = image_record.metadata.model_dump(mode="json")
            existing.size_bytes = image_record.metadata.size_bytes

        # Only update dates if not already extracted
        if not flags.get("dates_extracted", False) and image_record.dates:
            existing.dates = image_record.dates.model_dump(mode="json")

        # Check for thumbnail on disk (may have been generated by background job)
        thumbnail_exists = False
        thumbnail_full_path = get_thumbnail_path(
            image_record.checksum,
            self.catalog_path / "thumbnails",
        )
        if thumbnail_full_path.exists():
            thumbnail_exists = True
            if not existing.thumbnail_path:
                existing.thumbnail_path = str(
                    thumbnail_full_path.relative_to(self.catalog_path)
                )

        # Update processing flags based on current state
        processing_flags = existing.processing_flags or {}
        processing_flags["metadata_extracted"] = bool(
            image_record.metadata and image_record.metadata.exif
        ) or flags.get("metadata_extracted", False)
        processing_flags["dates_extracted"] = bool(
            image_record.dates
            and image_record.dates.selected_date
            and image_record.dates.confidence >= 70
        ) or flags.get("dates_extracted", False)
        processing_flags["thumbnail_generated"] = thumbnail_exists or bool(
            existing.thumbnail_path
        )
        processing_flags["ready_for_analysis"] = (
            processing_flags["metadata_extracted"]
            and processing_flags["dates_extracted"]
        )
        # Preserve other flags that may have been set by other tasks
        for key in [
            "hashes_computed",
            "quality_scored",
            "embedding_generated",
            "tags_applied",
        ]:
            if key not in processing_flags:
                processing_flags[key] = flags.get(key, False)

        # Populate queryable metadata columns if not already done
        if not flags.get("metadata_columns_populated", False):
            _populate_metadata_columns(
                existing, image_record.dates, image_record.metadata
            )
            processing_flags["metadata_columns_populated"] = True

        existing.processing_flags = processing_flags

        # Update timestamp
        existing.updated_at = datetime.utcnow()

    def _update_config(self, key: str, value: any) -> None:
        """
        Update or insert configuration value.

        Args:
            key: Configuration key
            value: Configuration value
        """
        print(f"DEBUG: _update_config called with key={key}, value={value}", flush=True)
        print(
            f"DEBUG: session={self.session}, catalog_id={self.catalog_id}", flush=True
        )

        # Check if there's a failed transaction and rollback if needed
        if self.session.in_transaction() and not self.session.is_active:
            print("DEBUG: Rolling back failed transaction", flush=True)
            self.session.rollback()

        # SQLAlchemy's JSONB type handles Python objects automatically
        # No need to json.dumps() - just pass the value directly
        config = (
            self.session.query(Config)
            .filter_by(catalog_id=self.catalog_id, key=key)
            .first()
        )
        print(f"DEBUG: Query completed, config={config}", flush=True)

        if config:
            config.value = value
            config.updated_at = datetime.utcnow()
        else:
            config = Config(
                catalog_id=self.catalog_id,
                key=key,
                value=value,
            )
            self.session.add(config)

        self.session.commit()

    def _update_statistics(self) -> None:
        """Update scan statistics in database."""
        # Get latest stats or create new
        stats = (
            self.session.query(Statistics)
            .filter_by(catalog_id=self.catalog_id)
            .order_by(Statistics.timestamp.desc())
            .first()
        )

        if not stats:
            stats = Statistics(catalog_id=self.catalog_id)
            self.session.add(stats)

        # Update counts
        stats.total_images = (
            self.session.query(Image)
            .filter_by(catalog_id=self.catalog_id, file_type="image")
            .count()
        )
        stats.total_videos = (
            self.session.query(Image)
            .filter_by(catalog_id=self.catalog_id, file_type="video")
            .count()
        )
        stats.images_scanned = stats.total_images + stats.total_videos
        stats.total_size_bytes = self.total_bytes

        # Update performance metrics
        if self.start_time and self.end_time:
            stats.processing_time_seconds = self.end_time - self.start_time
            if stats.processing_time_seconds > 0:
                stats.images_per_second = (
                    self.files_added / stats.processing_time_seconds
                )

        stats.timestamp = datetime.utcnow()
        self.session.commit()


# Compatibility wrapper for existing code
class ImageScanner:
    """
    Wrapper around ImageScannerORM for backward compatibility.

    This allows existing code to work while we migrate to ORM.
    """

    def __init__(
        self, catalog_db, workers: int = 4, perf_tracker=None, progress_callback=None
    ):
        """
        Initialize scanner with CatalogDB instance.

        Args:
            catalog_db: CatalogDB instance
            workers: Number of parallel workers
            perf_tracker: Optional performance tracker
            progress_callback: Optional callback(current, total, message) for progress updates
        """
        self.catalog = catalog_db
        self.workers = workers
        self.perf_tracker = perf_tracker
        self.progress_callback = progress_callback

        # Create ORM scanner
        if hasattr(catalog_db, "session") and catalog_db.session:
            # Get catalog path (test_path is already a Path object if set)
            if catalog_db._test_path:
                catalog_path = (
                    catalog_db._test_path
                    if isinstance(catalog_db._test_path, Path)
                    else Path(catalog_db._test_path)
                )
            else:
                catalog_path = Path.cwd()

            self.scanner = ImageScannerORM(
                session=catalog_db.session,
                catalog_id=catalog_db.catalog_id,
                catalog_path=catalog_path,
                workers=workers,
                perf_tracker=perf_tracker,
                progress_callback=progress_callback,
            )
        else:
            raise ValueError("CatalogDB must have an active session for ImageScanner")

    def scan_directories(self, directories: List[Path]) -> None:
        """Scan directories for images."""
        self.scanner.scan_directories(directories)

        # Copy statistics to self for compatibility
        self.files_added = self.scanner.files_added
        self.files_updated = self.scanner.files_updated
        self.files_skipped = self.scanner.files_skipped
        self.files_error = self.scanner.files_error
        self.total_bytes = self.scanner.total_bytes

    def _discover_files_incrementally(self, directory: Path):
        """Forward to ORM scanner for incremental file discovery."""
        return self.scanner._discover_files_incrementally(directory)
