"""Categorize images into system collections with 2-level hierarchy.

Top-level system categories (seeded at startup):
  Travel            → sub-collections: one per detected trip
  Family & Personal → sub-collections: decade buckets (1990s, 2000s, …)
  Work & Professional → sub-collections: Documents, Screenshots
  Archival          → sub-collections: Pre-1980, 1980s, 1990s
  Projects          → manual only

Detection signals:
  Travel     — GPS clusters >150 km from surrounding 30-day window centroid
  Archival   — capture_time before 2000-01-01
  Work       — content_class document/screenshot OR weekday 8am-6pm + camera EXIF
  Personal   — evenings 7pm-11pm or weekends + camera EXIF + not noise
"""

import json
import logging
import math
import time
import urllib.request
import uuid
from collections import Counter
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from ...db.connection import get_db_context
from ..background_jobs import should_stop_job, update_job_status
from ..types import JobContext

logger = logging.getLogger(__name__)

# Travel thresholds
TRAVEL_DISTANCE_KM = 150
TRAVEL_WINDOW_DAYS = 30
TRAVEL_MIN_IMAGES_PER_DAY = 2
TRIP_MAX_GAP_DAYS = 3  # days without photos before a new trip starts

# Content classes that indicate noise
NOISE_CLASSES = {"invalid", "meme", "received", "social_media"}


# ─────────────────────────── Geometry helpers ───────────────────────────


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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


# ─────────────────────────── Sub-collection upsert ───────────────────────────


def _ensure_subcollection(
    catalog_id: str,
    parent_id: str,
    system_key: str,
    name: str,
    description: str = "",
) -> str:
    """Get or create a system sub-collection by system_key. Returns collection id."""
    with get_db_context() as db:
        row = db.execute(
            text(
                "SELECT id FROM collections "
                "WHERE catalog_id = CAST(:cid AS uuid) AND system_key = :key"
            ),
            {"cid": catalog_id, "key": system_key},
        ).fetchone()
        if row:
            collection_id = str(row[0])
            db.execute(
                text(
                    "UPDATE collections SET name = :name, updated_at = NOW() "
                    "WHERE id = CAST(:id AS uuid)"
                ),
                {"name": name, "id": collection_id},
            )
            db.commit()
            return collection_id
        new_id = str(uuid.uuid4())
        db.execute(
            text(
                """
                INSERT INTO collections
                    (id, catalog_id, name, description, source, system_key, parent_id,
                     created_at, updated_at)
                VALUES
                    (CAST(:id AS uuid), CAST(:cid AS uuid), :name, :desc,
                     'system', :key, CAST(:pid AS uuid), NOW(), NOW())
                """
            ),
            {
                "id": new_id,
                "cid": catalog_id,
                "name": name,
                "desc": description,
                "key": system_key,
                "pid": parent_id,
            },
        )
        db.commit()
        return new_id


# ─────────────────────────── Membership upsert ───────────────────────────


def _upsert_memberships(
    catalog_id: str, collection_id: str, image_ids: List[str], confidence: float
) -> int:
    """Insert AI-suggested memberships (confirmed=False) skipping existing rows."""
    if not image_ids:
        return 0
    with get_db_context() as db:
        existing = {
            r[0]
            for r in db.execute(
                text(
                    "SELECT image_id FROM collection_images "
                    "WHERE collection_id = CAST(:cid AS uuid)"
                ),
                {"cid": collection_id},
            ).fetchall()
        }
        to_insert = [i for i in image_ids if i not in existing]
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
                    0, NOW(), :conf, false, 'system'
                ON CONFLICT (collection_id, image_id) DO NOTHING
                """
            ),
            {"cid": collection_id, "ids": to_insert, "conf": confidence},
        )
        db.commit()
        return len(to_insert)


# ─────────────────────────── Main entry point ───────────────────────────


def categorize_images_job(ctx: JobContext) -> Dict[str, Any]:
    catalog_id = ctx.catalog_id

    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={"percent": 0, "message": "Loading system collections"},
    )

    with get_db_context() as db:
        rows = db.execute(
            text(
                "SELECT system_key, id FROM collections "
                "WHERE catalog_id = CAST(:cid AS uuid) AND system_key IS NOT NULL "
                "AND parent_id IS NULL"
            ),
            {"cid": catalog_id},
        ).fetchall()
        sys_cols: Dict[str, str] = {r[0]: str(r[1]) for r in rows}

    if not sys_cols:
        return {"error": "no_system_collections"}

    results: Dict[str, Any] = {}

    # --- Archival ---
    if "archival" in sys_cols and not should_stop_job(ctx.job_id):
        update_job_status(
            ctx.job_id,
            "PROGRESS",
            progress={"percent": 10, "message": "Detecting archival photos"},
        )
        results["archival"] = _categorize_archival(catalog_id, sys_cols["archival"])

    # --- Travel ---
    if "travel" in sys_cols and not should_stop_job(ctx.job_id):
        update_job_status(
            ctx.job_id,
            "PROGRESS",
            progress={"percent": 25, "message": "Detecting travel"},
        )
        results["travel"] = _categorize_travel(catalog_id, sys_cols["travel"])

    # --- Work ---
    if "work_professional" in sys_cols and not should_stop_job(ctx.job_id):
        update_job_status(
            ctx.job_id,
            "PROGRESS",
            progress={"percent": 60, "message": "Detecting work content"},
        )
        results["work"] = _categorize_work(catalog_id, sys_cols["work_professional"])

    # --- Family & Personal ---
    if "family_personal" in sys_cols and not should_stop_job(ctx.job_id):
        update_job_status(
            ctx.job_id,
            "PROGRESS",
            progress={"percent": 80, "message": "Detecting personal moments"},
        )
        results["family"] = _categorize_family(catalog_id, sys_cols["family_personal"])

    if should_stop_job(ctx.job_id):
        return {"cancelled": True}

    update_job_status(
        ctx.job_id, "PROGRESS", progress={"percent": 100, "message": "Done"}
    )
    results["total"] = sum(
        v if isinstance(v, int) else v.get("total", 0) for v in results.values()
    )
    return results


# ─────────────────────────── Archival ───────────────────────────


def _categorize_archival(catalog_id: str, archival_id: str) -> Dict[str, int]:
    with get_db_context() as db:
        rows = db.execute(
            text(
                """
                SELECT id, EXTRACT(YEAR FROM capture_time)::int AS yr
                FROM images
                WHERE catalog_id = CAST(:cid AS uuid)
                  AND capture_time IS NOT NULL
                  AND EXTRACT(YEAR FROM capture_time) < 2000
                  AND status_id NOT IN ('rejected', 'archived')
                """
            ),
            {"cid": catalog_id},
        ).fetchall()

    buckets: Dict[str, List[str]] = {"pre_1980": [], "1980s": [], "1990s": []}
    for img_id, yr in rows:
        if yr < 1980:
            buckets["pre_1980"].append(img_id)
        elif yr < 1990:
            buckets["1980s"].append(img_id)
        else:
            buckets["1990s"].append(img_id)

    specs = [
        ("pre_1980", "archival:pre_1980", "Pre-1980", "Film era and earlier."),
        ("1980s", "archival:1980s", "1980s", ""),
        ("1990s", "archival:1990s", "1990s", ""),
    ]
    totals: Dict[str, int] = {}
    for bucket_key, sys_key, name, desc in specs:
        ids = buckets[bucket_key]
        if not ids:
            continue
        sub_id = _ensure_subcollection(catalog_id, archival_id, sys_key, name, desc)
        totals[bucket_key] = _upsert_memberships(catalog_id, sub_id, ids, 0.95)

    return {"total": sum(totals.values()), **totals}


# ─────────────────────────── Travel ───────────────────────────


_MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]

_geocode_cache: Dict[str, Optional[str]] = {}


def _reverse_geocode_city(lat: float, lon: float) -> Optional[str]:
    """Return city/town name for coordinates via Nominatim. Returns None on failure."""
    key = f"{lat:.2f},{lon:.2f}"
    if key in _geocode_cache:
        return _geocode_cache[key]
    url = (
        f"https://nominatim.openstreetmap.org/reverse"
        f"?format=json&lat={lat:.6f}&lon={lon:.6f}&zoom=10"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Lumina/2.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        addr = data.get("address", {})
        city = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("county")
        )
        _geocode_cache[key] = city
        return city
    except Exception:
        _geocode_cache[key] = None
        return None


def _trip_name(start: date, end: date, location: Optional[str] = None) -> str:
    """Human-readable trip name. Prepends location when available."""
    if start.year == end.year:
        if start.month == end.month:
            date_part = (
                f"{_MONTHS[start.month - 1]} {start.day}–{end.day}, {start.year}"
            )
        else:
            date_part = (
                f"{_MONTHS[start.month - 1]}–{_MONTHS[end.month - 1]} {start.year}"
            )
    else:
        date_part = f"{_MONTHS[start.month - 1]} {start.year} – {_MONTHS[end.month - 1]} {end.year}"
    if location:
        return f"{location} – {date_part}"
    return date_part


def _categorize_travel(catalog_id: str, travel_id: str) -> Dict[str, Any]:
    with get_db_context() as db:
        rows = db.execute(
            text(
                """
                SELECT id, capture_time, latitude, longitude
                FROM images
                WHERE catalog_id = CAST(:cid AS uuid)
                  AND latitude IS NOT NULL AND longitude IS NOT NULL
                  AND capture_time IS NOT NULL
                  AND status_id NOT IN ('rejected', 'archived')
                ORDER BY capture_time
                """
            ),
            {"cid": catalog_id},
        ).fetchall()

    if len(rows) < 10:
        return {"total": 0}

    timeline = [
        {"id": r[0], "ts": r[1], "lat": float(r[2]), "lon": float(r[3])} for r in rows
    ]

    # Step 1: flag travel images using GPS delta from surrounding window
    window_td = timedelta(days=TRAVEL_WINDOW_DAYS)
    travel_ids: set = set()

    for img in timeline:
        ts = img["ts"]
        same_day = ts.date()
        surrounding = [
            (t["lat"], t["lon"])
            for t in timeline
            if ts - window_td <= t["ts"] <= ts + window_td
            and t["ts"].date() != same_day
        ]
        if len(surrounding) < 5:
            continue
        c = _centroid(surrounding)
        if (
            c
            and _haversine_km(img["lat"], img["lon"], c[0], c[1]) >= TRAVEL_DISTANCE_KM
        ):
            travel_ids.add(img["id"])

    # Require TRAVEL_MIN_IMAGES_PER_DAY per day to filter GPS glitches
    day_counts: Counter = Counter(
        img["ts"].date() for img in timeline if img["id"] in travel_ids
    )
    qualified_days = {
        d for d, n in day_counts.items() if n >= TRAVEL_MIN_IMAGES_PER_DAY
    }
    travel_images = [
        img
        for img in timeline
        if img["id"] in travel_ids and img["ts"].date() in qualified_days
    ]

    if not travel_images:
        return {"total": 0}

    # Step 2: group consecutive travel days into trips (gap <= TRIP_MAX_GAP_DAYS)
    # Store (image_id, lat, lon) per day for centroid lookup
    by_date: Dict[date, List[Tuple[str, float, float]]] = {}
    for img in travel_images:
        by_date.setdefault(img["ts"].date(), []).append(
            (img["id"], img["lat"], img["lon"])
        )

    sorted_days = sorted(by_date.keys())
    trips: List[List[date]] = []
    current: List[date] = [sorted_days[0]]
    for d in sorted_days[1:]:
        if (d - current[-1]).days <= TRIP_MAX_GAP_DAYS:
            current.append(d)
        else:
            trips.append(current)
            current = [d]
    trips.append(current)

    # Step 3: create a sub-collection per trip
    trip_count = 0
    for trip_days in trips:
        start_d, end_d = trip_days[0], trip_days[-1]
        sys_key = f"travel_trip:{start_d.isoformat()}_{end_d.isoformat()}"

        # Compute trip centroid and reverse-geocode for a location name
        all_pts = [(lat, lon) for d in trip_days for _, lat, lon in by_date.get(d, [])]
        location: Optional[str] = None
        if all_pts:
            c = _centroid(all_pts)
            if c:
                location = _reverse_geocode_city(c[0], c[1])
                time.sleep(1.1)  # Nominatim rate limit: 1 req/s

        name = _trip_name(start_d, end_d, location)
        sub_id = _ensure_subcollection(
            catalog_id, travel_id, sys_key, name, f"Trip detected {start_d} – {end_d}"
        )
        ids = [img_id for d in trip_days for img_id, _, _ in by_date.get(d, [])]
        n = _upsert_memberships(catalog_id, sub_id, ids, 0.80)
        trip_count += n
        logger.info(f"Travel trip '{name}': {n} images")

    return {"trips": len(trips), "total": trip_count}


# ─────────────────────────── Work & Professional ───────────────────────────


def _categorize_work(catalog_id: str, work_id: str) -> Dict[str, int]:
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

    docs: List[str] = []
    screenshots: List[str] = []
    work_general: List[str] = []

    for r in rows:
        img_id, ts, content_class, camera_make = r
        if content_class == "document":
            docs.append(img_id)
        elif content_class == "screenshot":
            screenshots.append(img_id)
        elif (
            ts is not None
            and ts.weekday() < 5
            and 8 <= ts.hour < 18
            and camera_make is not None
            and content_class not in NOISE_CLASSES
        ):
            work_general.append(img_id)

    totals: Dict[str, int] = {}
    specs = [
        (docs, "work:documents", "Documents", "Scanned documents, PDFs, whiteboards."),
        (
            screenshots,
            "work:screenshots",
            "Screenshots",
            "App screenshots and screen captures.",
        ),
        (
            work_general,
            "work:work_hours",
            "Work Hours",
            "Photos taken on weekdays during business hours.",
        ),
    ]
    for ids, sys_key, name, desc in specs:
        if not ids:
            continue
        sub_id = _ensure_subcollection(catalog_id, work_id, sys_key, name, desc)
        totals[name] = _upsert_memberships(catalog_id, sub_id, ids, 0.70)

    return {"total": sum(totals.values()), **totals}


# ─────────────────────────── Family & Personal ───────────────────────────


def _categorize_family(catalog_id: str, family_id: str) -> Dict[str, int]:
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

    # Group by decade
    by_decade: Dict[str, List[str]] = {}
    for r in rows:
        img_id, ts, _, content_class = r
        if content_class in NOISE_CLASSES:
            continue
        is_weekend = ts.weekday() >= 5
        is_evening = 19 <= ts.hour < 23
        if not (is_weekend or is_evening):
            continue
        decade = f"{(ts.year // 10) * 10}s"
        by_decade.setdefault(decade, []).append(img_id)

    totals: Dict[str, int] = {}
    for decade, ids in sorted(by_decade.items()):
        if not ids:
            continue
        sys_key = f"family:{decade}"
        sub_id = _ensure_subcollection(
            catalog_id,
            family_id,
            sys_key,
            decade,
            f"Personal photos from the {decade}.",
        )
        totals[decade] = _upsert_memberships(catalog_id, sub_id, ids, 0.65)

    return {"total": sum(totals.values()), **totals}
