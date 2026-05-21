"""Categorize images into system collections.

Signals used per category:

  Travel            — GPS clusters sustained >100 km from surrounding 30-day window centroid
  Family & Personal — weekends or evenings (7pm-11pm) + has camera EXIF + not noise
  Work & Professional — content_class document/screenshot OR weekday business hours + camera EXIF
  Archival          — capture_time before 2000-01-01
  Projects          — manual only, no auto-detection
"""

import logging
import math
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from ...db.connection import get_db_context
from ..background_jobs import should_stop_job, update_job_status
from ..types import JobContext

logger = logging.getLogger(__name__)

# Minimum number of images in a day to consider it a "travel day"
TRAVEL_MIN_IMAGES_PER_DAY = 2
# Distance threshold to flag as travel (km)
TRAVEL_DISTANCE_KM = 150
# Window for computing "normal" location centroid (days each side)
TRAVEL_WINDOW_DAYS = 30
# Content classes that indicate noise (exclude from Family & Work signals)
NOISE_CLASSES = {"invalid", "meme", "received", "social_media"}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _centroid(points: List[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    if not points:
        return None
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


def categorize_images_job(ctx: JobContext) -> Dict[str, Any]:
    """Main entry point: assign images to system collections."""
    catalog_id = ctx.catalog_id

    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={"percent": 0, "message": "Loading catalog data"},
    )

    with get_db_context() as db:
        # Fetch collection IDs for all system keys in this catalog
        rows = db.execute(
            text(
                "SELECT system_key, id FROM collections "
                "WHERE catalog_id = CAST(:cid AS uuid) AND system_key IS NOT NULL"
            ),
            {"cid": catalog_id},
        ).fetchall()
        sys_collections: Dict[str, str] = {r[0]: str(r[1]) for r in rows}

    if not sys_collections:
        logger.warning(
            f"No system collections for catalog {catalog_id} — seeding skipped"
        )
        return {"error": "no_system_collections"}

    results: Dict[str, int] = {}

    if should_stop_job(ctx.job_id):
        return {"cancelled": True}

    # --- Archival ---
    if "archival" in sys_collections:
        update_job_status(
            ctx.job_id,
            "PROGRESS",
            progress={"percent": 10, "message": "Detecting archival photos"},
        )
        n = _categorize_archival(catalog_id, sys_collections["archival"])
        results["archival"] = n
        logger.info(f"Archival: {n} images")

    if should_stop_job(ctx.job_id):
        return {"cancelled": True}

    # --- Travel ---
    if "travel" in sys_collections:
        update_job_status(
            ctx.job_id,
            "PROGRESS",
            progress={"percent": 25, "message": "Detecting travel"},
        )
        n = _categorize_travel(catalog_id, sys_collections["travel"])
        results["travel"] = n
        logger.info(f"Travel: {n} images")

    if should_stop_job(ctx.job_id):
        return {"cancelled": True}

    # --- Work & Professional ---
    if "work_professional" in sys_collections:
        update_job_status(
            ctx.job_id,
            "PROGRESS",
            progress={"percent": 55, "message": "Detecting work content"},
        )
        n = _categorize_work(catalog_id, sys_collections["work_professional"])
        results["work_professional"] = n
        logger.info(f"Work & Professional: {n} images")

    if should_stop_job(ctx.job_id):
        return {"cancelled": True}

    # --- Family & Personal ---
    if "family_personal" in sys_collections:
        update_job_status(
            ctx.job_id,
            "PROGRESS",
            progress={"percent": 75, "message": "Detecting personal moments"},
        )
        n = _categorize_family_personal(catalog_id, sys_collections["family_personal"])
        results["family_personal"] = n
        logger.info(f"Family & Personal: {n} images")

    update_job_status(
        ctx.job_id, "PROGRESS", progress={"percent": 100, "message": "Done"}
    )
    results["total"] = sum(results.values())
    return results


# ─────────────────────────── Archival ───────────────────────────


def _categorize_archival(catalog_id: str, collection_id: str) -> int:
    with get_db_context() as db:
        rows = db.execute(
            text(
                """
                SELECT id FROM images
                WHERE catalog_id = CAST(:cid AS uuid)
                  AND capture_time IS NOT NULL
                  AND EXTRACT(YEAR FROM capture_time) < 2000
                  AND status_id NOT IN ('rejected', 'archived')
                """
            ),
            {"cid": catalog_id},
        ).fetchall()
        image_ids = [r[0] for r in rows]
        return _upsert_memberships(db, collection_id, image_ids, confidence=0.95)


# ─────────────────────────── Travel ───────────────────────────


def _categorize_travel(catalog_id: str, collection_id: str) -> int:
    """
    For each image with GPS, compute whether it's >TRAVEL_DISTANCE_KM from
    the centroid of GPS images in the surrounding ±TRAVEL_WINDOW_DAYS window.
    Images meeting this threshold AND in a day with >= TRAVEL_MIN_IMAGES_PER_DAY
    qualifying images are flagged as travel.
    """
    with get_db_context() as db:
        rows = db.execute(
            text(
                """
                SELECT id, capture_time, latitude, longitude
                FROM images
                WHERE catalog_id = CAST(:cid AS uuid)
                  AND latitude IS NOT NULL
                  AND longitude IS NOT NULL
                  AND capture_time IS NOT NULL
                  AND status_id NOT IN ('rejected', 'archived')
                ORDER BY capture_time
                """
            ),
            {"cid": catalog_id},
        ).fetchall()

    if len(rows) < 10:
        return 0

    # Build timeline: [{id, ts, lat, lon}]
    timeline = [
        {"id": r[0], "ts": r[1], "lat": float(r[2]), "lon": float(r[3])} for r in rows
    ]

    window_td = timedelta(days=TRAVEL_WINDOW_DAYS)
    travel_ids: List[str] = []

    for img in timeline:
        ts = img["ts"]
        lo, hi = ts - window_td, ts + window_td

        # Surrounding images (exclude same day to avoid anchoring)
        same_day = ts.date()
        surrounding = [
            (t["lat"], t["lon"])
            for t in timeline
            if lo <= t["ts"] <= hi and t["ts"].date() != same_day
        ]
        if len(surrounding) < 5:
            continue

        centroid = _centroid(surrounding)
        if centroid is None:
            continue

        dist = _haversine_km(img["lat"], img["lon"], centroid[0], centroid[1])
        if dist >= TRAVEL_DISTANCE_KM:
            travel_ids.append(img["id"])

    # Require at least TRAVEL_MIN_IMAGES_PER_DAY travel-flagged images per day
    # (filters out isolated outliers like a one-off GPS glitch)
    from collections import Counter

    day_counts: Counter = Counter()
    travel_id_set = set(travel_ids)
    for img in timeline:
        if img["id"] in travel_id_set:
            day_counts[img["ts"].date()] += 1

    qualified_days = {
        day for day, cnt in day_counts.items() if cnt >= TRAVEL_MIN_IMAGES_PER_DAY
    }
    day_map = {img["id"]: img["ts"].date() for img in timeline}
    final_ids = [iid for iid in travel_ids if day_map.get(iid) in qualified_days]

    with get_db_context() as db:
        return _upsert_memberships(db, collection_id, final_ids, confidence=0.80)


# ─────────────────────────── Work & Professional ───────────────────────────


def _categorize_work(catalog_id: str, collection_id: str) -> int:
    with get_db_context() as db:
        rows = db.execute(
            text(
                """
                SELECT id, capture_time, content_class, camera_make
                FROM images
                WHERE catalog_id = CAST(:cid AS uuid)
                  AND status_id NOT IN ('rejected', 'archived')
                """
            ),
            {"cid": catalog_id},
        ).fetchall()

    work_ids: List[str] = []
    for r in rows:
        img_id, ts, content_class, camera_make = r[0], r[1], r[2], r[3]
        is_doc = content_class in ("document", "screenshot")
        is_work_hours = (
            ts is not None
            and ts.weekday() < 5  # Mon–Fri
            and 8 <= ts.hour < 18  # 8am–6pm
            and camera_make is not None  # has camera EXIF
            and content_class not in NOISE_CLASSES
            and content_class != "screenshot"  # screenshots handled via doc flag
        )
        if is_doc or is_work_hours:
            work_ids.append(img_id)

    with get_db_context() as db:
        return _upsert_memberships(db, collection_id, work_ids, confidence=0.70)


# ─────────────────────────── Family & Personal ───────────────────────────


def _categorize_family_personal(catalog_id: str, collection_id: str) -> int:
    with get_db_context() as db:
        rows = db.execute(
            text(
                """
                SELECT id, capture_time, camera_make, content_class
                FROM images
                WHERE catalog_id = CAST(:cid AS uuid)
                  AND camera_make IS NOT NULL
                  AND capture_time IS NOT NULL
                  AND status_id NOT IN ('rejected', 'archived')
                """
            ),
            {"cid": catalog_id},
        ).fetchall()

    personal_ids: List[str] = []
    for r in rows:
        img_id, ts, _, content_class = r[0], r[1], r[2], r[3]
        if content_class in NOISE_CLASSES:
            continue
        is_weekend = ts.weekday() >= 5  # Sat/Sun
        is_evening = 19 <= ts.hour < 23  # 7pm–11pm
        if is_weekend or is_evening:
            personal_ids.append(img_id)

    with get_db_context() as db:
        return _upsert_memberships(db, collection_id, personal_ids, confidence=0.65)


# ─────────────────────────── Shared helper ───────────────────────────


def _upsert_memberships(
    db: Any, collection_id: str, image_ids: List[str], confidence: float
) -> int:
    """Insert or update AI-suggested memberships (confirmed=False, source='system')."""
    if not image_ids:
        return 0

    # Fetch already-existing memberships so we don't downgrade confirmed ones
    existing = {
        r[0]: r[1]
        for r in db.execute(
            text(
                "SELECT image_id, confirmed FROM collection_images "
                "WHERE collection_id = CAST(:cid AS uuid)"
            ),
            {"cid": collection_id},
        ).fetchall()
    }

    to_insert: List[str] = []
    for iid in image_ids:
        if iid not in existing:
            to_insert.append(iid)
        # If already there (any confirmation state), leave it alone

    if not to_insert:
        return 0

    db.execute(
        text(
            """
            INSERT INTO collection_images
                (id, collection_id, image_id, position, added_at,
                 confidence, confirmed, source)
            SELECT
                gen_random_uuid(),
                CAST(:cid AS uuid),
                unnest(CAST(:ids AS text[])),
                0,
                NOW(),
                :conf,
                false,
                'system'
            ON CONFLICT (collection_id, image_id) DO NOTHING
            """
        ),
        {"cid": collection_id, "ids": to_insert, "conf": confidence},
    )
    db.commit()
    return len(to_insert)
