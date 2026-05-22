"""Cloud backup job using rclone.

Syncs the catalog's organized_directory to one or more rclone remotes.
Requires rclone to be installed and configured (rclone config).

Parameters (ctx.parameters):
    destinations (list[str]):  rclone remote paths, e.g.
        ["s3:mybucket/photos", "b2:mybucket/photos", "gdrive:Backups/photos"]
        If omitted, reads from catalog.backup_destinations.
    dry_run (bool, default False): pass --dry-run to rclone (no data transferred)
    transfers (int, default 8): parallel transfer count

Exit codes from rclone:
    0  = success
    1  = uncorrected errors
    5  = couldn't copy/delete some files (partial)
    6  = no changes (--dry-run or nothing to transfer)
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def backup_catalog_job(ctx) -> Dict[str, Any]:
    from sqlalchemy import text

    from ...db import get_db_context
    from ...jobs.coordinator import should_stop_job, update_job_status

    catalog_id: str = ctx.catalog_id
    dry_run: bool = ctx.get("dry_run", False)
    transfers: int = ctx.get("transfers", 8)
    param_destinations: List[str] = ctx.get("destinations", [])

    # Verify rclone is available
    if not shutil.which("rclone"):
        raise RuntimeError(
            "rclone is not installed or not on PATH. "
            "Install rclone (https://rclone.org) and configure remotes with 'rclone config'."
        )

    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={"percent": 0, "message": "Loading catalog"},
    )

    with get_db_context() as db:
        row = db.execute(
            text(
                "SELECT organized_directory, backup_destinations FROM catalogs "
                "WHERE id = CAST(:cid AS uuid)"
            ),
            {"cid": catalog_id},
        ).fetchone()

    if not row:
        raise ValueError(f"Catalog {catalog_id} not found")

    organized_dir = row.organized_directory
    if not organized_dir or not Path(organized_dir).is_dir():
        raise ValueError(
            "Catalog has no organized_directory or it does not exist. "
            "Run the Organize job first."
        )

    # Resolve destination list: params override catalog-level config
    destinations: List[str] = param_destinations
    if not destinations and row.backup_destinations:
        raw = row.backup_destinations
        if isinstance(raw, str):
            raw = json.loads(raw)
        destinations = raw or []

    if not destinations:
        raise ValueError(
            "No backup destinations configured. "
            "Pass destinations as job parameters or set them in catalog settings."
        )

    results: List[Dict[str, Any]] = []

    for i, dest in enumerate(destinations):
        if should_stop_job(ctx.job_id):
            break

        pct = int((i / len(destinations)) * 90)
        update_job_status(
            ctx.job_id,
            "PROGRESS",
            progress={"percent": pct, "message": f"Syncing to {dest}"},
        )

        cmd = [
            "rclone",
            "sync",
            organized_dir,
            dest,
            "--transfers",
            str(transfers),
            "--stats-log-level",
            "NOTICE",
            "--stats",
            "10s",
            "-v",
        ]
        if dry_run:
            cmd.append("--dry-run")

        logger.info("Running: %s", " ".join(cmd))

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600 * 6,  # 6-hour hard cap
            )
            success = proc.returncode in (0, 6)  # 6 = nothing to do
            results.append(
                {
                    "destination": dest,
                    "success": success,
                    "returncode": proc.returncode,
                    "stderr_tail": proc.stderr[-2000:] if proc.stderr else "",
                }
            )
            if not success:
                logger.error(
                    "rclone exited %d for %s:\n%s",
                    proc.returncode,
                    dest,
                    proc.stderr[-2000:],
                )
        except subprocess.TimeoutExpired:
            results.append(
                {
                    "destination": dest,
                    "success": False,
                    "returncode": -1,
                    "stderr_tail": "Timed out after 6 hours",
                }
            )
        except Exception as e:
            results.append(
                {
                    "destination": dest,
                    "success": False,
                    "returncode": -1,
                    "stderr_tail": str(e),
                }
            )

    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={"percent": 100, "message": "Done"},
    )

    all_ok = all(r["success"] for r in results)
    return {
        "dry_run": dry_run,
        "source": organized_dir,
        "destinations": results,
        "all_succeeded": all_ok,
    }
