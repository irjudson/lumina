"""ML Enrichment Job — discover visual and temporal/geo image clusters.

Produces ml_groups rows (pending human naming) using:
  1. Visual clustering — scipy agglomerative on CLIP embeddings
  2. Temporal+geo clustering — time-gap + GPS proximity session detection
  3. Label hints — qwen3-vl scene description for each cluster's samples
"""

import base64
import json
import logging
import math
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx
import numpy as np
from sqlalchemy import text

from lumina.db import get_db_context
from lumina.jobs.background_jobs import update_job_status
from lumina.jobs.types import JobContext

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://ollama:11434"
VISION_MODEL = "qwen3-vl:latest"

# Clustering parameters
VISUAL_SAMPLE_SIZE = 5000  # Images to sample for visual clustering
VISUAL_DISTANCE_THRESHOLD = 0.40  # Cosine distance cutoff (lower = more similar)
MIN_CLUSTER_SIZE = 8  # Minimum images to create an ml_group
TEMPORAL_GAP_HOURS = 4.0  # Hour gap to split temporal sessions
GEO_GAP_KM = 50.0  # Km gap to split geo sessions


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance between two vectors."""
    sim = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10)
    return float(1.0 - sim)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _fetch_visual_sample(
    catalog_id: str, limit: int
) -> List[Tuple[str, np.ndarray, Optional[str]]]:
    """Return list of (image_id, embedding, thumbnail_path) for images with embeddings
    not yet in a pending ml_group of method clip_agglomerative."""
    with get_db_context() as db:
        rows = db.execute(
            text(
                "SELECT i.id, i.clip_embedding, i.thumbnail_path"
                " FROM images i"
                " WHERE i.catalog_id = CAST(:cid AS uuid)"
                "   AND i.clip_embedding IS NOT NULL"
                "   AND NOT EXISTS ("
                "     SELECT 1 FROM ml_group_images mgi"
                "     JOIN ml_groups mg ON mg.id = mgi.group_id"
                "     WHERE mgi.image_id = i.id"
                "       AND mg.method = 'clip_agglomerative'"
                "       AND mg.status = 'pending'"
                "   )"
                " ORDER BY i.id"
                " LIMIT :lim"
            ),
            {"cid": catalog_id, "lim": limit},
        ).fetchall()
    result = []
    for image_id, emb_raw, thumb in rows:
        if emb_raw is None:
            continue
        try:
            if hasattr(emb_raw, "tolist"):
                floats = emb_raw.tolist()
            elif isinstance(emb_raw, str):
                floats = json.loads(emb_raw)
            else:
                floats = list(emb_raw)
            vec = np.array(floats, dtype=np.float32)
        except Exception:
            continue
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        result.append((str(image_id), vec, thumb))
    return result


def _agglomerative_clusters(
    items: List[Tuple[str, np.ndarray, Optional[str]]],
    threshold: float,
) -> List[List[Tuple[str, float, Optional[str]]]]:
    """Cluster items using scipy agglomerative clustering (Ward with cosine distances).

    Returns list of clusters, each a list of (image_id, score, thumbnail_path).
    """
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import pdist

    if len(items) < 2:
        return []

    ids = [item[0] for item in items]
    thumbs = [item[2] for item in items]
    matrix = np.stack([item[1] for item in items])

    # Pairwise cosine distances
    dist_vec = pdist(matrix, metric="cosine")

    # Agglomerative linkage (average linkage works well with cosine)
    Z = linkage(dist_vec, method="average")
    labels = fcluster(Z, t=threshold, criterion="distance")

    # Group by label
    cluster_map: Dict[int, List] = {}
    for i, lbl in enumerate(labels):
        cluster_map.setdefault(lbl, []).append((ids[i], thumbs[i]))

    # Convert to output format with uniform score
    clusters = []
    for members in cluster_map.values():
        clusters.append([(iid, 1.0, thumb) for iid, thumb in members])
    return clusters


def _run_visual_clustering(
    catalog_id: str,
    job_id: str,
    min_size: int,
    sample_size: int,
    threshold: float,
) -> int:
    """Cluster CLIP embeddings, write new ml_groups. Returns group count created."""
    update_job_status(
        job_id,
        "PROGRESS",
        progress={"phase": "visual_fetch", "message": "Fetching CLIP embeddings…"},
    )
    items = _fetch_visual_sample(catalog_id, sample_size)
    if not items:
        logger.info("No unprocessed embeddings found for visual clustering")
        return 0

    logger.info(f"Running visual clustering on {len(items)} embeddings")
    update_job_status(
        job_id,
        "PROGRESS",
        progress={
            "phase": "visual_cluster",
            "message": f"Clustering {len(items):,} images…",
        },
    )

    clusters = _agglomerative_clusters(items, threshold)
    groups_created = 0

    with get_db_context() as db:
        for cluster in clusters:
            if len(cluster) < min_size:
                continue

            group_id = str(uuid.uuid4())
            sample_ids = [m[0] for m in cluster[:5]]

            db.execute(
                text(
                    "INSERT INTO ml_groups"
                    " (id, catalog_id, method, image_count, sample_image_ids)"
                    " VALUES (CAST(:id AS uuid), CAST(:cid AS uuid),"
                    " 'clip_agglomerative', :cnt, CAST(:samples AS jsonb))"
                ),
                {
                    "id": group_id,
                    "cid": catalog_id,
                    "cnt": len(cluster),
                    "samples": json.dumps(sample_ids),
                },
            )

            for image_id, score, _ in cluster:
                db.execute(
                    text(
                        "INSERT INTO ml_group_images (group_id, image_id, score)"
                        " VALUES (CAST(:gid AS uuid), :iid, :score)"
                        " ON CONFLICT DO NOTHING"
                    ),
                    {"gid": group_id, "iid": image_id, "score": score},
                )

            groups_created += 1
        db.commit()

    logger.info(f"Created {groups_created} visual clusters")
    return groups_created


def _fetch_temporal_geo_images(
    catalog_id: str,
) -> List[Dict[str, Any]]:
    """Fetch images with temporal data, optionally GPS, ordered by time."""
    with get_db_context() as db:
        rows = db.execute(
            text(
                "SELECT i.id, i.capture_time, i.latitude, i.longitude,"
                " i.thumbnail_path"
                " FROM images i"
                " WHERE i.catalog_id = CAST(:cid AS uuid)"
                "   AND i.capture_time IS NOT NULL"
                "   AND i.capture_time BETWEEN '1990-01-01' AND '2030-12-31'"
                "   AND NOT EXISTS ("
                "     SELECT 1 FROM ml_group_images mgi"
                "     JOIN ml_groups mg ON mg.id = mgi.group_id"
                "     WHERE mgi.image_id = i.id"
                "       AND mg.method = 'temporal_geo'"
                "       AND mg.status = 'pending'"
                "   )"
                " ORDER BY i.capture_time"
            ),
            {"cid": catalog_id},
        ).fetchall()
    return [
        {
            "id": str(r[0]),
            "time": r[1],
            "lat": r[2],
            "lon": r[3],
            "thumb": r[4],
        }
        for r in rows
    ]


def _run_temporal_geo_clustering(
    catalog_id: str,
    job_id: str,
    min_size: int,
    gap_hours: float,
    gap_km: float,
) -> int:
    """Session-based temporal+geo clustering. Returns group count created."""
    update_job_status(
        job_id,
        "PROGRESS",
        progress={"phase": "temporal_fetch", "message": "Fetching temporal data…"},
    )
    images = _fetch_temporal_geo_images(catalog_id)
    if not images:
        return 0

    update_job_status(
        job_id,
        "PROGRESS",
        progress={
            "phase": "temporal_cluster",
            "message": f"Segmenting {len(images):,} images by time/geo…",
        },
    )

    sessions: List[List[Dict]] = []
    current: List[Dict] = [images[0]]

    for img in images[1:]:
        prev = current[-1]
        dt_hours = (
            (img["time"] - prev["time"]).total_seconds() / 3600
            if img["time"] and prev["time"]
            else 0
        )
        geo_split = False
        if (
            img["lat"] is not None
            and img["lon"] is not None
            and prev["lat"] is not None
            and prev["lon"] is not None
        ):
            dist_km = _haversine_km(prev["lat"], prev["lon"], img["lat"], img["lon"])
            geo_split = dist_km > gap_km

        if dt_hours > gap_hours or geo_split:
            sessions.append(current)
            current = [img]
        else:
            current.append(img)

    sessions.append(current)

    # Filter out sessions that overlap with travel folk_tags (already handled)
    groups_created = 0
    with get_db_context() as db:
        for session in sessions:
            if len(session) < min_size:
                continue

            group_id = str(uuid.uuid4())
            sample_ids = [s["id"] for s in session[:5]]

            # Build signals summary
            times = [s["time"] for s in session if s["time"]]
            lats = [s["lat"] for s in session if s["lat"] is not None]
            lons = [s["lon"] for s in session if s["lon"] is not None]
            signals: Dict[str, Any] = {
                "start": times[0].isoformat() if times else None,
                "end": times[-1].isoformat() if times else None,
            }
            if lats:
                signals["center_lat"] = sum(lats) / len(lats)
                signals["center_lon"] = sum(lons) / len(lons)

            db.execute(
                text(
                    "INSERT INTO ml_groups"
                    " (id, catalog_id, method, image_count,"
                    "  sample_image_ids, signals)"
                    " VALUES (CAST(:id AS uuid), CAST(:cid AS uuid),"
                    " 'temporal_geo', :cnt,"
                    " CAST(:samples AS jsonb), CAST(:signals AS jsonb))"
                ),
                {
                    "id": group_id,
                    "cid": catalog_id,
                    "cnt": len(session),
                    "samples": json.dumps(sample_ids),
                    "signals": json.dumps(signals),
                },
            )

            for img in session:
                db.execute(
                    text(
                        "INSERT INTO ml_group_images (group_id, image_id)"
                        " VALUES (CAST(:gid AS uuid), :iid)"
                        " ON CONFLICT DO NOTHING"
                    ),
                    {"gid": group_id, "iid": img["id"]},
                )

            groups_created += 1
        db.commit()

    logger.info(f"Created {groups_created} temporal/geo sessions")
    return groups_created


def _ollama_label_hint(image_path: str) -> Optional[str]:
    """Ask qwen3-vl to describe a scene in a few words. Returns None on failure."""
    try:
        import os

        if not os.path.exists(image_path):
            return None

        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        ext = image_path.rsplit(".", 1)[-1].lower()
        mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"

        payload = {
            "model": VISION_MODEL,
            "prompt": (
                "Describe this photo in 4–6 words — focus on subject and setting."
                " Reply with ONLY those words, no punctuation."
            ),
            "images": [f"data:{mime};base64,{b64}"],
            "stream": False,
            "options": {"num_predict": 20, "temperature": 0.2},
        }

        resp = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip() or None
    except Exception as e:
        logger.debug(f"Label hint failed for {image_path}: {e}")
        return None


def _add_label_hints(catalog_id: str, job_id: str) -> int:
    """Add qwen3-vl label hints to pending groups that have sample images."""
    with get_db_context() as db:
        groups = db.execute(
            text(
                "SELECT id, sample_image_ids FROM ml_groups"
                " WHERE catalog_id = CAST(:cid AS uuid)"
                "   AND status = 'pending'"
                "   AND label_hint IS NULL"
                " ORDER BY created_at DESC"
                " LIMIT 50"
            ),
            {"cid": catalog_id},
        ).fetchall()

    if not groups:
        return 0

    update_job_status(
        job_id,
        "PROGRESS",
        progress={
            "phase": "label_hints",
            "message": f"Generating label hints for {len(groups)} groups…",
        },
    )

    hints_added = 0
    for group_id, sample_ids_raw in groups:
        sample_ids = sample_ids_raw if isinstance(sample_ids_raw, list) else []
        if not sample_ids:
            continue

        # Get source paths for samples
        with get_db_context() as db:
            paths = db.execute(
                text(
                    "SELECT source_path FROM images"
                    " WHERE id = ANY(:ids) AND source_path IS NOT NULL"
                    " LIMIT 3"
                ),
                {"ids": sample_ids},
            ).fetchall()

        hint = None
        for (path,) in paths:
            hint = _ollama_label_hint(path)
            if hint:
                break

        if hint:
            with get_db_context() as db:
                db.execute(
                    text(
                        "UPDATE ml_groups SET label_hint = :hint"
                        " WHERE id = CAST(:gid AS uuid)"
                    ),
                    {"hint": hint, "gid": str(group_id)},
                )
                db.commit()
            hints_added += 1

    logger.info(f"Added {hints_added} label hints")
    return hints_added


def enrich_ml_groups_job(ctx: JobContext) -> Dict[str, Any]:
    """Run ML enrichment — visual clustering, temporal/geo, label hints."""
    catalog_id = ctx.catalog_id
    params = ctx.parameters

    skip_visual = params.get("skip_visual", False)
    skip_temporal = params.get("skip_temporal", False)
    skip_hints = params.get("skip_hints", False)
    sample_size = int(params.get("sample_size", VISUAL_SAMPLE_SIZE))
    min_size = int(params.get("min_cluster_size", MIN_CLUSTER_SIZE))
    threshold = float(params.get("visual_threshold", VISUAL_DISTANCE_THRESHOLD))
    gap_hours = float(params.get("gap_hours", TEMPORAL_GAP_HOURS))
    gap_km = float(params.get("gap_km", GEO_GAP_KM))

    visual_groups = 0
    temporal_groups = 0
    hints_added = 0

    if not skip_visual:
        visual_groups = _run_visual_clustering(
            catalog_id, ctx.job_id, min_size, sample_size, threshold
        )

    if not skip_temporal:
        temporal_groups = _run_temporal_geo_clustering(
            catalog_id, ctx.job_id, min_size, gap_hours, gap_km
        )

    if not skip_hints:
        hints_added = _add_label_hints(catalog_id, ctx.job_id)

    total_groups = visual_groups + temporal_groups
    logger.info(
        f"ML enrichment complete: {visual_groups} visual, "
        f"{temporal_groups} temporal/geo, {hints_added} hints"
    )

    return {
        "visual_groups": visual_groups,
        "temporal_groups": temporal_groups,
        "hints_added": hints_added,
        "total_groups": total_groups,
    }
