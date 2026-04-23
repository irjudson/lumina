"""File organization job definition.

Reorganizes catalog files into a standard output directory structure:

  <organized_directory>/
    YYYY/MM-DD/YYYYMMDD_HHMMSS[_NN].ext   ← resolved + iffy images
    _date_only/YYYY/MM-DD/                 ← midnight timestamps (date known, time synthetic)
    _rejected/YYYY/MM-DD/                  ← rejected images
    _archived/YYYY/MM-DD/                  ← archived images
    _unresolved/unknown/                   ← no usable date

Date confidence tiers (stored in processing_flags after organization):
  resolved  - EXIF DateTimeOriginal/CreateDate with real time component
  iffy      - filename, directory, filesystem, or exif:ModifyDate source
  date_only - any source where time is synthetic midnight 00:00:00
  unresolved - no usable date at all

Excluded from organization entirely: paths containing '#recycle' or 'Possible Duplicate'.

Collision resolution: auto-sequence suffix _01, _02, ...
Operation modes: copy (default, safe) or move.
Scope modes: new (unorganized only), iffy, unresolved, all.
"""

import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Confidence tier labels
TIER_RESOLVED = "resolved"
TIER_IFFY = "iffy"
TIER_DATE_ONLY = "date_only"  # date known but time is synthetic midnight 00:00:00
TIER_UNRESOLVED = "unresolved"

# capture_time_source prefixes/values that map to each tier
RESOLVED_SOURCE_PREFIX = "exif:"
# ModifyDate is not a reliable capture time — demote to iffy
IFFY_EXIF_SOURCES = {"exif:ModifyDate"}
IFFY_SOURCES = {"filename", "directory", "filesystem"}

# Paths containing these substrings are excluded from organization
EXCLUDED_PATH_SUBSTRINGS = {"#recycle", "Possible Duplicate"}


def _is_midnight(capture_time) -> bool:
    """Return True if capture_time is exactly midnight (synthetic date-only value)."""
    return (
        capture_time.hour == 0 and capture_time.minute == 0 and capture_time.second == 0
    )


def _get_confidence_tier(capture_time_source: Optional[str], capture_time) -> str:
    """Map capture_time_source to a confidence tier string."""
    if capture_time is None:
        return TIER_UNRESOLVED
    if capture_time_source in IFFY_EXIF_SOURCES:
        return TIER_IFFY
    if capture_time_source and capture_time_source.startswith(RESOLVED_SOURCE_PREFIX):
        # Real EXIF capture date — but if time is midnight it may be date-only
        if _is_midnight(capture_time):
            return TIER_DATE_ONLY
        return TIER_RESOLVED
    # Non-EXIF sources (filename, directory, filesystem) — iffy or date_only
    if _is_midnight(capture_time):
        return TIER_DATE_ONLY
    return TIER_IFFY


def _get_subdirectory(status_id: str, tier: str) -> str:
    """Get the top-level subdirectory prefix for an image."""
    if status_id == "rejected":
        return "_rejected"
    if status_id == "archived":
        return "_archived"
    if tier == TIER_UNRESOLVED:
        return "_unresolved"
    if tier == TIER_DATE_ONLY:
        return "_date_only"
    return ""  # primary tree (resolved + iffy)


def _make_date_dir(capture_time) -> str:
    """Format capture_time into YYYY/MM-DD directory path."""
    if capture_time is None:
        return "unknown"
    return f"{capture_time.year:04d}/{capture_time.month:02d}-{capture_time.day:02d}"


def _make_filename(capture_time, suffix: str) -> str:
    """Format capture_time into YYYYMMDD_HHMMSS.ext filename."""
    if capture_time is None:
        return f"unknown{suffix}"
    ts = capture_time.strftime("%Y%m%d_%H%M%S")
    return f"{ts}{suffix}"


def _resolve_collision(base_path: Path, filename: str) -> str:
    """
    If base_path/filename already exists in planned_paths set, add _NN suffix.
    Returns the resolved filename (without directory).
    """
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = filename
    counter = 1
    while (base_path / candidate).exists():
        candidate = f"{stem}_{counter:02d}{suffix}"
        counter += 1
        if counter > 9999:
            raise ValueError(f"Too many collisions for {base_path / filename}")
    return candidate


def _resolve_collision_in_plan(
    dest_dir: Path, filename: str, planned: set
) -> Tuple[str, bool]:
    """
    Resolve collision against both filesystem and planned paths.
    Returns (resolved_filename, was_collision).
    """
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = filename
    counter = 1
    while str(dest_dir / candidate) in planned or (dest_dir / candidate).exists():
        candidate = f"{stem}_{counter:02d}{suffix}"
        counter += 1
        if counter > 9999:
            raise ValueError(f"Too many collisions for {dest_dir / filename}")
    return candidate, (candidate != filename)


def _plan_organization(
    images: List[Any],
    output_dir: Path,
    scope: str,
    pending_duplicate_ids: Optional[set] = None,
    confirmed_duplicate_size_bytes: int = 0,
) -> Dict[str, Any]:
    """
    Build the full organization plan without touching the filesystem.

    Returns a dict with:
      summary: counts by category
      operations: list of {image_id, source_path, dest_path, tier, status, collision,
                           has_pending_duplicate}
      exceptions: items needing attention (iffy, unresolved, collision)

    pending_duplicate_ids: set of image IDs that have unreviewed duplicate candidates.
      When scope == 'skip_pending_duplicates', these images are excluded from the plan.
      Otherwise they are included but flagged in operations and counted in summary.
    confirmed_duplicate_size_bytes: total bytes of images already confirmed as duplicates
      (archived) — used for the savings advisory in the preview.
    """
    if pending_duplicate_ids is None:
        pending_duplicate_ids = set()

    summary = {
        "total": 0,
        "excluded_paths": 0,  # files excluded due to path filters (#recycle, Possible Duplicate, etc.)
        "skipped_already_organized": 0,
        "skipped_out_of_scope": 0,  # in library but excluded by scope filter (e.g. non-resolved in resolved_only)
        "skipped_pending_duplicates": 0,  # excluded because they have unreviewed duplicate candidates
        "will_organize": 0,  # files that will actually be moved/copied
        "pending_duplicate_count": 0,  # being organized but have unreviewed duplicate candidates
        "pending_duplicate_size_bytes": 0,
        "confirmed_duplicate_size_bytes": confirmed_duplicate_size_bytes,
        "resolved": 0,
        "iffy": 0,
        "date_only": 0,
        "unresolved": 0,
        "rejected": 0,
        "archived": 0,
        "collisions_resolved": 0,
        "errors": 0,
        # Storage / risk fields
        "total_size_bytes": 0,  # bytes that would be copied/moved
        "missing_checksum_count": 0,  # files with no checksum — can't verify after move
        "available_bytes": None,  # free space on output filesystem (None if undetectable)
    }
    operations = []
    exceptions = []
    planned_dest_paths: set = set()

    import os
    import shutil

    # Walk up to find the nearest existing ancestor of output_dir for disk checks
    check_path = output_dir
    while not check_path.exists() and check_path != check_path.parent:
        check_path = check_path.parent

    # Available space on the output filesystem
    try:
        summary["available_bytes"] = shutil.disk_usage(check_path).free
    except OSError:
        pass

    # Determine if source and destination are on the same filesystem device.
    # Same device → move is an atomic rename (safe). Different device → copy+delete (riskier).
    try:
        output_dev = os.stat(check_path).st_dev
    except OSError:
        output_dev = None

    for image in images:
        # Exclude recycle bins and duplicate staging directories entirely
        source_str = str(image.source_path)
        if any(excl in source_str for excl in EXCLUDED_PATH_SUBSTRINGS):
            summary["excluded_paths"] += 1
            continue

        summary["total"] += 1

        # Scope filtering
        tier = _get_confidence_tier(image.capture_time_source, image.capture_time)
        flags = image.processing_flags or {}

        # Pending duplicate scope: skip images with unreviewed candidates
        if scope == "skip_pending_duplicates" and image.id in pending_duplicate_ids:
            summary["skipped_pending_duplicates"] += 1
            continue

        if scope == "new" and image.organized_path is not None:
            summary["skipped_already_organized"] += 1
            continue
        if scope == "resolved_only":
            # Only unorganized images whose date is fully resolved (EXIF, real time component)
            if tier != TIER_RESOLVED:
                summary["skipped_out_of_scope"] += 1
                continue
            if image.organized_path is not None:
                summary["skipped_already_organized"] += 1
                continue
        if scope == "iffy":
            if (
                image.organized_path is None
                or flags.get("organization_confidence") != TIER_IFFY
            ):
                if (
                    image.organized_path is not None
                    and flags.get("organization_confidence") == TIER_IFFY
                ):
                    pass  # process it
                elif image.organized_path is None:
                    pass  # unorganized, also process
                else:
                    summary["skipped_already_organized"] += 1
                    continue
        if scope == "unresolved":
            if (
                image.organized_path is None
                or flags.get("organization_confidence") != TIER_UNRESOLVED
            ):
                if (
                    image.organized_path is not None
                    and flags.get("organization_confidence") == TIER_UNRESOLVED
                ):
                    pass
                elif image.organized_path is None:
                    pass
                else:
                    summary["skipped_already_organized"] += 1
                    continue

        # Determine output subdirectory
        subdir = _get_subdirectory(image.status_id or "active", tier)
        date_dir = _make_date_dir(image.capture_time)
        source_path = Path(image.source_path)
        suffix = source_path.suffix.lower()
        filename = _make_filename(image.capture_time, suffix)

        if subdir:
            dest_dir = output_dir / subdir / date_dir
        else:
            dest_dir = output_dir / date_dir

        # Resolve collision
        try:
            resolved_filename, had_collision = _resolve_collision_in_plan(
                dest_dir, filename, planned_dest_paths
            )
        except ValueError as e:
            summary["errors"] += 1
            exceptions.append(
                {
                    "image_id": image.id,
                    "source_path": str(image.source_path),
                    "proposed_destination": str(dest_dir / filename),
                    "issue": "error",
                    "detail": str(e),
                }
            )
            continue

        dest_path = dest_dir / resolved_filename
        planned_dest_paths.add(str(dest_path))

        # Track counts
        if image.status_id == "rejected":
            summary["rejected"] += 1
        elif image.status_id == "archived":
            summary["archived"] += 1
        elif tier == TIER_UNRESOLVED:
            summary["unresolved"] += 1
        elif tier == TIER_DATE_ONLY:
            summary["date_only"] += 1
        elif tier == TIER_IFFY:
            summary["iffy"] += 1
        else:
            summary["resolved"] += 1

        if had_collision:
            summary["collisions_resolved"] += 1

        # Storage accounting
        if image.size_bytes:
            summary["total_size_bytes"] += image.size_bytes
        if not image.checksum:
            summary["missing_checksum_count"] += 1

        # Cross-filesystem detection (sample first file's source device)
        if output_dev is not None and "cross_filesystem" not in summary:
            try:
                src_dev = os.stat(image.source_path).st_dev
                summary["cross_filesystem"] = src_dev != output_dev
            except OSError:
                pass

        has_pending_dup = image.id in pending_duplicate_ids
        if has_pending_dup:
            summary["pending_duplicate_count"] += 1
            if image.size_bytes:
                summary["pending_duplicate_size_bytes"] += image.size_bytes

        op = {
            "image_id": image.id,
            "source_path": str(image.source_path),
            "dest_path": str(dest_path),
            "tier": tier,
            "status": image.status_id or "active",
            "collision": had_collision,
            "has_pending_duplicate": has_pending_dup,
        }
        operations.append(op)
        summary["will_organize"] += 1

        # Build exceptions list (iffy, unresolved, collision)
        issues = []
        if tier == TIER_IFFY:
            issues.append("iffy_date")
        if tier == TIER_DATE_ONLY:
            issues.append("date_only")
        if tier == TIER_UNRESOLVED:
            issues.append("unresolved")
        if had_collision:
            issues.append("collision_resolved")

        if issues:
            exceptions.append(
                {
                    "image_id": image.id,
                    "source_path": str(image.source_path),
                    "proposed_destination": str(dest_path),
                    "issue": ", ".join(issues),
                    "detail": f"source={image.capture_time_source or 'none'}",
                }
            )

    return {
        "summary": summary,
        "operations": operations,
        "exceptions": exceptions,
    }


def discover_images(catalog_id: str) -> List[str]:
    """Discover all image IDs in the catalog."""
    from lumina.db.models import Image
    from lumina.db.session import get_db_session

    with get_db_session() as session:
        images = session.query(Image.id).filter(Image.catalog_id == catalog_id).all()
        return [row.id for row in images]


def process_image(
    image_id: str,
    catalog_id: str,
    output_dir: str,
    operation: str,
    plan: Dict[str, Any],
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Execute a single image file operation (copy or move).
    Updates organized_path and processing_flags in the DB on success.
    """
    from lumina.db.models import Image
    from lumina.db.session import get_db_session
    from lumina.shared.media_utils import compute_checksum

    # Find this image's operation in the plan
    op = next((o for o in plan["operations"] if o["image_id"] == image_id), None)
    if op is None:
        return {"image_id": image_id, "skipped": True, "reason": "not_in_plan"}

    source = Path(op["source_path"])
    dest = Path(op["dest_path"])

    if not source.exists():
        return {"image_id": image_id, "error": f"Source not found: {source}"}

    # Create destination directory
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        if operation == "copy":
            shutil.copy2(str(source), str(dest))
        else:  # move
            shutil.move(str(source), str(dest))

        # Verify checksum
        dest_checksum = compute_checksum(dest)
        with get_db_session() as session:
            image = session.query(Image).filter(Image.id == image_id).first()
            if image and image.checksum != dest_checksum:
                dest.unlink(missing_ok=True)
                return {
                    "image_id": image_id,
                    "error": f"Checksum mismatch after {operation}",
                }

            # Update DB paths and flags
            if image:
                image.organized_path = str(dest)
                flags = dict(image.processing_flags or {})
                flags["organized"] = True
                flags["organization_confidence"] = op["tier"]
                flags["organization_source"] = None  # populated below
                image.processing_flags = flags
                session.commit()

        return {"image_id": image_id, "dest_path": str(dest), "tier": op["tier"]}

    except Exception as e:
        logger.error(f"Error organizing {source}: {e}")
        return {"image_id": image_id, "error": str(e)}


def finalize_organize(
    results: List[Dict[str, Any]],
    catalog_id: str,
) -> Dict[str, Any]:
    """Aggregate results from all image operations."""
    organized = sum(1 for r in results if "dest_path" in r)
    skipped = sum(1 for r in results if r.get("skipped"))
    errors = [r for r in results if "error" in r]

    return {
        "organized": organized,
        "skipped": skipped,
        "error_count": len(errors),
        "error_details": [
            {"image_id": e["image_id"], "error": e["error"]} for e in errors
        ],
    }
