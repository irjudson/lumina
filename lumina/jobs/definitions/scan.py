"""Scan job definition.

Discovers and processes media files in source directories.

Note: This job definition uses the ParallelJob framework, but all execution
is now sequential (serial). The ParallelJob name is kept for backward compatibility.
"""

import hashlib
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..framework import ParallelJob, register_job

# Media file extensions supported for scanning
MEDIA_EXTENSIONS = {
    # Images
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".heic",
    ".heif",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
    # RAW formats
    ".raw",
    ".cr2",
    ".cr3",
    ".nef",
    ".arw",
    ".dng",
    ".orf",
    ".rw2",
    # Videos
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".m4v",
    ".wmv",
    ".webm",
}


def discover_files(
    catalog_id: str,
    source_dirs_provider: Optional[Callable[[str], List[str]]] = None,
) -> List[str]:
    """Discover files to scan in catalog source directories.

    Args:
        catalog_id: The catalog UUID
        source_dirs_provider: Optional function to get source directories
                            (defaults to database lookup)

    Returns:
        List of file paths to process
    """
    # Get source directories
    if source_dirs_provider:
        source_dirs = source_dirs_provider(catalog_id)
    else:
        # Default: use database lookup
        from lumina.db.models import Catalog
        from lumina.db.session import get_db_session

        with get_db_session() as session:
            catalog = session.query(Catalog).filter(Catalog.id == catalog_id).first()
            source_dirs = catalog.source_directories if catalog else []

    # Also load the catalog's organized_directory so we can exclude it during scan
    organized_dir: Optional[Path] = None
    try:
        from lumina.db.models import Catalog as _Catalog
        from lumina.db.session import get_db_session as _get_db_session

        with _get_db_session() as session:
            cat = session.query(_Catalog).filter(_Catalog.id == catalog_id).first()
            if cat and cat.organized_directory:
                organized_dir = Path(cat.organized_directory).resolve()
    except Exception:
        pass  # non-fatal; worst case we scan the output dir too

    files = []
    for dir_path in source_dirs:
        path = Path(dir_path)
        if not (path.exists() and path.is_dir()):
            continue
        for file in path.rglob("*"):
            if not file.is_file():
                continue
            if file.suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            # Skip anything inside the organized output directory
            if organized_dir is not None:
                try:
                    file.resolve().relative_to(organized_dir)
                    continue  # file is inside the output dir — skip it
                except ValueError:
                    pass  # not under organized_dir — include it
            files.append(str(file))

    return files


def process_file(
    file_path: str,
    catalog_id: str,
    generate_thumbnail: bool = True,
    extract_metadata: bool = True,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Process a single media file.

    Args:
        file_path: Path to the file
        catalog_id: The catalog UUID
        generate_thumbnail: Whether to generate thumbnail
        extract_metadata: Whether to extract EXIF metadata
        **kwargs: Additional processing options

    Returns:
        Processing result dict with checksum, size, metadata, etc.
    """
    path = Path(file_path)

    # Compute checksum
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        # Read in chunks for large files
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    checksum = hasher.hexdigest()

    # Determine file type
    suffix = path.suffix.lower()
    if suffix in {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv", ".webm"}:
        file_type = "video"
    else:
        file_type = "image"

    result: Dict[str, Any] = {
        "path": file_path,
        "checksum": checksum,
        "size_bytes": path.stat().st_size,
        "file_type": file_type,
    }

    # Extract metadata if requested
    if extract_metadata:
        try:
            from lumina.analysis.metadata import MetadataExtractor
            from lumina.core.types import FileType as CoreFileType

            ft = CoreFileType.VIDEO if file_type == "video" else CoreFileType.IMAGE
            with MetadataExtractor() as extractor:
                meta = extractor.extract_metadata(path, ft)
                # Convert Pydantic model to dict for storage
                result["metadata"] = (
                    meta.model_dump() if hasattr(meta, "model_dump") else {}
                )
                # Extract dates separately
                date_info = extractor.extract_dates(path, meta)
                result["dates"] = (
                    date_info.model_dump() if hasattr(date_info, "model_dump") else {}
                )
        except Exception as e:
            result["metadata_error"] = str(e)

    # Note: Thumbnail generation requires output_path configuration
    # This will be wired up when integrating with the catalog system
    if generate_thumbnail:
        # Placeholder - actual implementation needs output directory
        result["thumbnail_path"] = None

    return result


def finalize_scan(
    results: List[Dict[str, Any]],
    catalog_id: str,
) -> Dict[str, Any]:
    """Finalize scan job - compute statistics.

    Args:
        results: All processing results
        catalog_id: The catalog UUID

    Returns:
        Summary statistics
    """
    total_size = sum(r.get("size_bytes", 0) for r in results)
    images = sum(1 for r in results if r.get("file_type") == "image")
    videos = sum(1 for r in results if r.get("file_type") == "video")

    return {
        "total_files": len(results),
        "total_images": images,
        "total_videos": videos,
        "total_size_bytes": total_size,
    }


# Register the scan job with the global registry
# Note: max_workers is ignored - all processing is sequential
scan_job: ParallelJob[str] = register_job(
    ParallelJob(
        name="scan",
        discover=discover_files,
        process=process_file,
        finalize=finalize_scan,
        batch_size=500,
        max_workers=1,  # Ignored - sequential processing only
    )
)
