"""Camera import job — copies device files to organized_directory then catalogs them."""

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from lumina.db import get_db_context

from ..background_jobs import should_stop_job, update_job_status
from ..types import JobContext

logger = logging.getLogger(__name__)

VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv", ".webm"}


def _get_capture_time(source_path: Path, extractor=None):
    """Return EXIF capture time or mtime fallback."""
    try:
        from lumina.core.types import FileType

        ft = (
            FileType.VIDEO
            if source_path.suffix.lower() in VIDEO_SUFFIXES
            else FileType.IMAGE
        )
        if extractor is not None:
            meta = extractor.extract_metadata(source_path, ft)
            dates = extractor.extract_dates(source_path, meta)
            if dates and dates.selected_date:
                return dates.selected_date
        else:
            from lumina.analysis.metadata import MetadataExtractor

            with MetadataExtractor() as ext:
                meta = ext.extract_metadata(source_path, ft)
                dates = ext.extract_dates(source_path, meta)
                if dates and dates.selected_date:
                    return dates.selected_date
    except Exception:
        pass
    return datetime.fromtimestamp(source_path.stat().st_mtime)


def _dest_path(output_dir: Path, source_path: Path, capture_time) -> Path:
    """Build YYYY/MM-DD/YYYYMMDD_HHMMSS.ext destination path."""
    from lumina.jobs.definitions.organize import _make_date_dir, _make_filename

    date_dir = _make_date_dir(capture_time)
    filename = _make_filename(capture_time, source_path.suffix.lower())
    dest = output_dir / date_dir / filename

    # Collision resolution
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        counter = 1
        while dest.exists():
            dest = dest.parent / f"{stem}_{counter}{suffix}"
            counter += 1
    return dest


def camera_import_job(ctx: JobContext) -> Dict[str, Any]:
    """Copy device files into organized_directory then catalog each one."""
    file_paths = ctx.parameters.get("file_paths", [])
    delete_source = ctx.parameters.get("delete_source", False)

    from lumina.db.models import Catalog

    with get_db_context() as db:
        catalog = db.query(Catalog).filter(Catalog.id == ctx.catalog_id).first()
        if not catalog:
            return {"error": "catalog_not_found"}
        if not catalog.organized_directory:
            return {"error": "no_organized_directory"}
        output_dir = Path(catalog.organized_directory)

    # Validate output directory — create if missing, fail fast if inaccessible
    if not output_dir.exists():
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return {"error": "output_directory_not_accessible", "detail": str(e)}

    total = len(file_paths)
    copied = cataloged = failed = skipped = 0
    imported_image_ids: list[str] = []

    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={
            "current": 0,
            "total": total,
            "percent": 0,
            "message": "Starting import...",
        },
    )

    from lumina.analysis.metadata import MetadataExtractor
    from lumina.analysis.scanner import _process_file_sequential
    from lumina.db import CatalogDB

    with MetadataExtractor() as extractor, CatalogDB(ctx.catalog_id) as catalog_db:
        for idx, file_path_str in enumerate(file_paths):
            if should_stop_job(ctx.job_id):
                break

            source = Path(file_path_str)
            if not source.exists():
                failed += 1
                continue

            try:
                capture_time = _get_capture_time(source, extractor)
                dest = _dest_path(output_dir, source, capture_time)
                dest.parent.mkdir(parents=True, exist_ok=True)

                shutil.copy2(str(source), str(dest))
                copied += 1

                this_cataloged = False
                result = _process_file_sequential(dest, extractor)
                if result is not None:
                    from sqlalchemy import text as sa_text

                    image_record, _ = result
                    catalog_db.add_image(image_record)
                    # Mark organized_path so discover dedup can detect re-imports
                    catalog_db.session.execute(
                        sa_text("UPDATE images SET organized_path = :p WHERE id = :id"),
                        {"p": str(dest), "id": image_record.id},
                    )
                    catalog_db.session.commit()
                    imported_image_ids.append(image_record.id)
                    cataloged += 1
                    this_cataloged = True
                else:
                    skipped += 1

                if delete_source and this_cataloged:
                    source.unlink()

            except Exception as e:
                logger.error(f"Failed to import {file_path_str}: {e}")
                failed += 1

            percent = int((idx + 1) / total * 100) if total else 100
            update_job_status(
                ctx.job_id,
                "PROGRESS",
                progress={
                    "current": idx + 1,
                    "total": total,
                    "percent": percent,
                    "message": f"Imported {copied} of {total}...",
                    "rate": 0,
                },
            )

    if imported_image_ids:
        _upsert_last_import_collection(ctx.catalog_id, imported_image_ids)

    return {
        "copied": copied,
        "cataloged": cataloged,
        "failed": failed,
        "skipped": skipped,
        "total": total,
    }


def _upsert_last_import_collection(catalog_id: str, image_ids: list[str]) -> None:
    """Replace the 'last_import' system collection with the just-imported images."""
    import uuid as _uuid
    from datetime import datetime

    from sqlalchemy import text as sa_text

    now = datetime.utcnow().isoformat()
    with get_db_context() as db:
        row = db.execute(
            sa_text(
                "SELECT id FROM collections WHERE catalog_id = CAST(:cid AS uuid)"
                " AND system_key = 'last_import' LIMIT 1"
            ),
            {"cid": catalog_id},
        ).first()

        if row:
            collection_id = str(row[0])
            db.execute(
                sa_text(
                    "UPDATE collections SET name = :name, updated_at = :now WHERE id = CAST(:id AS uuid)"
                ),
                {"name": "Last Import", "now": now, "id": collection_id},
            )
        else:
            collection_id = str(_uuid.uuid4())
            db.execute(
                sa_text(
                    "INSERT INTO collections (id, catalog_id, name, source, system_key, created_at, updated_at)"
                    " VALUES (CAST(:id AS uuid), CAST(:cid AS uuid), :name, 'system', 'last_import', :now, :now)"
                ),
                {
                    "id": collection_id,
                    "cid": catalog_id,
                    "name": "Last Import",
                    "now": now,
                },
            )

        db.execute(
            sa_text(
                "DELETE FROM collection_images WHERE collection_id = CAST(:cid AS uuid)"
            ),
            {"cid": collection_id},
        )

        for image_id in image_ids:
            db.execute(
                sa_text(
                    "INSERT INTO collection_images (id, collection_id, image_id, added_at, position)"
                    " VALUES (CAST(:id AS uuid), CAST(:cid AS uuid), :iid, :now, 0)"
                    " ON CONFLICT DO NOTHING"
                ),
                {
                    "id": str(_uuid.uuid4()),
                    "cid": collection_id,
                    "iid": image_id,
                    "now": now,
                },
            )

        db.commit()
