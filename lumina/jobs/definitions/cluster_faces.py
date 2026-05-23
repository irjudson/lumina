"""Cluster face embeddings into per-person sub-collections under People.

Algorithm:
  1. Load all face embeddings for the catalog (from the faces table)
  2. L2-normalise embeddings so cosine distance = euclidean distance on unit sphere
  3. DBSCAN with eps~0.4 and min_samples=2 groups similar faces into clusters
  4. Each cluster → one "Person N" sub-collection under the People category
  5. Images whose faces belong to a cluster are added to that person's collection
     as confirmed=False AI suggestions (user can rename + confirm)
  6. Singleton faces (noise in DBSCAN) are left uncategorised

Re-running is safe: existing confirmed memberships are preserved; only new
images are added (upsert via ON CONFLICT DO NOTHING).
"""

import logging
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional

import numpy as np

from ...db.connection import get_db_context
from ..background_jobs import should_stop_job, update_job_status
from ..types import JobContext

logger = logging.getLogger(__name__)

# DBSCAN tuning
DBSCAN_EPS = 0.40  # cosine distance threshold (~cos 66° ≈ clearly same person)
DBSCAN_MIN_SAMPLES = 2  # minimum faces to form a cluster
# Minimum images per person-cluster before we bother creating a sub-collection
MIN_IMAGES_PER_PERSON = 1


def cluster_faces_job(ctx: JobContext) -> Dict[str, Any]:
    catalog_id = ctx.catalog_id

    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={"percent": 0, "message": "Loading face embeddings"},
    )

    # --- Load embeddings and existing person assignments ---
    with get_db_context() as db:
        from sqlalchemy import text

        rows = db.execute(
            text(
                """
                SELECT f.id, f.image_id, f.embedding, f.person_collection_id
                FROM faces f
                WHERE f.catalog_id = CAST(:cid AS uuid)
                  AND f.embedding IS NOT NULL
                """
            ),
            {"cid": catalog_id},
        ).fetchall()

    if len(rows) < DBSCAN_MIN_SAMPLES:
        return {
            "people_created": 0,
            "images_categorized": 0,
            "message": "Not enough faces to cluster",
        }

    face_ids = [str(r[0]) for r in rows]
    image_ids = [r[1] for r in rows]
    embeddings_raw = [r[2] for r in rows]
    # Existing assignments from prior run + user merges (training signal)
    prior_assignments: Dict[str, str] = {
        str(r[0]): str(r[3]) for r in rows if r[3] is not None
    }

    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={"percent": 10, "message": f"Clustering {len(face_ids):,} faces"},
    )

    # Parse pgvector text format "[0.1,0.2,...]" → numpy array
    embeddings = _parse_embeddings(embeddings_raw)
    # L2 normalise
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    embeddings = embeddings / norms

    if should_stop_job(ctx.job_id):
        return {"cancelled": True}

    # --- DBSCAN clustering ---
    labels = _dbscan(embeddings, eps=DBSCAN_EPS, min_samples=DBSCAN_MIN_SAMPLES)

    unique_clusters = sorted(set(labels) - {-1})
    logger.info(f"DBSCAN: {len(unique_clusters)} clusters from {len(face_ids)} faces")

    if not unique_clusters:
        return {"people_created": 0, "images_categorized": 0}

    # --- Find People top-level collection ---
    people_col_id = _get_people_collection_id(catalog_id)
    if not people_col_id:
        return {
            "error": "People system collection not found; run categorize_images first"
        }

    if should_stop_job(ctx.job_id):
        return {"cancelled": True}

    # --- Get existing person sub-collections (for stable re-numbering) ---
    existing_person_count = _count_person_subcollections(catalog_id, people_col_id)

    # --- Apply user-merge constraints: if faces in a cluster already point to a
    #     user-confirmed collection (from a prior merge), re-use that collection.
    #     This makes user corrections persist across re-clustering runs. ---
    cluster_override: Dict[int, str] = _merge_constraint_map(
        labels, face_ids, prior_assignments
    )

    # --- Create/update per-person sub-collections ---
    people_created = 0
    images_categorized = 0

    for cluster_idx, cluster_label in enumerate(unique_clusters):
        if should_stop_job(ctx.job_id):
            break

        percent = 20 + int((cluster_idx / len(unique_clusters)) * 70)
        if cluster_idx % 10 == 0:
            update_job_status(
                ctx.job_id,
                "PROGRESS",
                progress={
                    "percent": percent,
                    "message": f"Assigning person {cluster_idx + 1}/{len(unique_clusters)}",
                },
            )

        # Collect unique image IDs for this cluster
        cluster_image_ids = list(
            {image_ids[i] for i, lbl in enumerate(labels) if lbl == cluster_label}
        )
        if len(cluster_image_ids) < MIN_IMAGES_PER_PERSON:
            continue

        # Check if user has previously merged this cluster into an existing person
        if cluster_label in cluster_override:
            person_col_id = cluster_override[cluster_label]
        else:
            # Stable system_key: based on cluster centroid representative face id
            rep_face_idx = _representative_face(embeddings, labels, cluster_label)
            rep_face_id = face_ids[rep_face_idx]
            sys_key = f"people_person:{rep_face_id}"

            person_num = existing_person_count + people_created + 1
            person_col_id = _ensure_person_collection(
                catalog_id, people_col_id, sys_key, f"Person {person_num}"
            )

        # Update face rows to point at this collection
        _assign_faces_to_person(
            catalog_id, cluster_label, labels, face_ids, person_col_id
        )

        # Add images to the person's collection as AI suggestions
        n = _upsert_image_memberships(catalog_id, person_col_id, cluster_image_ids)
        images_categorized += n
        if n > 0:
            people_created += 1

    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={"percent": 100, "message": "Done"},
    )

    return {
        "people_created": people_created,
        "images_categorized": images_categorized,
        "clusters_found": len(unique_clusters),
        "faces_processed": len(face_ids),
    }


# ─────────────────────────── Helpers ───────────────────────────


def _merge_constraint_map(
    labels: np.ndarray,
    face_ids: List[str],
    prior_assignments: Dict[str, str],
    min_vote_fraction: float = 0.5,
) -> Dict[int, str]:
    """Return {cluster_label: person_collection_id} for clusters where a majority
    of faces already point to an existing (user-confirmed) collection.

    This lets user-corrected merges survive DBSCAN re-runs: after merging cluster
    A into cluster B, all A faces have person_collection_id=B. If DBSCAN splits
    them again, this function reunites them into B.
    """
    overrides: Dict[int, str] = {}
    unique = sorted(set(labels) - {-1})
    for lbl in unique:
        cluster_face_ids = [face_ids[i] for i, l in enumerate(labels) if l == lbl]
        votes = [
            prior_assignments[f] for f in cluster_face_ids if f in prior_assignments
        ]
        if not votes:
            continue
        top_col, top_count = Counter(votes).most_common(1)[0]
        if top_count / len(cluster_face_ids) >= min_vote_fraction:
            overrides[lbl] = top_col
    return overrides


def _parse_embeddings(raw: List[Any]) -> np.ndarray:
    """Convert pgvector string or list representations to numpy array."""
    result = []
    for r in raw:
        if isinstance(r, str):
            # e.g. "[0.1,0.2,...]"
            r = r.strip("[]")
            result.append([float(x) for x in r.split(",")])
        elif hasattr(r, "__iter__"):
            result.append(list(r))
        else:
            result.append([0.0] * 512)
    return np.array(result, dtype=np.float32)


def _dbscan(embeddings: np.ndarray, eps: float, min_samples: int) -> np.ndarray:
    """Run DBSCAN with cosine metric. Returns label array (-1 = noise)."""
    from sklearn.cluster import DBSCAN

    clustering = DBSCAN(
        eps=eps,
        min_samples=min_samples,
        metric="cosine",
        algorithm="brute",
        n_jobs=-1,
    )
    return clustering.fit_predict(embeddings)


def _representative_face(
    embeddings: np.ndarray, labels: np.ndarray, cluster_label: int
) -> int:
    """Index of the face closest to the cluster centroid."""
    indices = np.where(labels == cluster_label)[0]
    cluster_embs = embeddings[indices]
    centroid = cluster_embs.mean(axis=0)
    centroid /= np.linalg.norm(centroid) + 1e-9
    sims = cluster_embs @ centroid
    best_local = int(np.argmax(sims))
    return int(indices[best_local])


def _get_people_collection_id(catalog_id: str) -> Optional[str]:
    from sqlalchemy import text

    with get_db_context() as db:
        row = db.execute(
            text(
                "SELECT id FROM collections "
                "WHERE catalog_id = CAST(:cid AS uuid) AND system_key = 'people' AND parent_id IS NULL"
            ),
            {"cid": catalog_id},
        ).fetchone()
        return str(row[0]) if row else None


def _count_person_subcollections(catalog_id: str, people_col_id: str) -> int:
    from sqlalchemy import text

    with get_db_context() as db:
        row = db.execute(
            text(
                "SELECT COUNT(*) FROM collections "
                "WHERE catalog_id = CAST(:cid AS uuid) AND parent_id = CAST(:pid AS uuid)"
            ),
            {"cid": catalog_id, "pid": people_col_id},
        ).fetchone()
        return int(row[0]) if row else 0


def _ensure_person_collection(
    catalog_id: str, people_col_id: str, sys_key: str, name: str
) -> str:
    from sqlalchemy import text

    with get_db_context() as db:
        row = db.execute(
            text(
                "SELECT id FROM collections "
                "WHERE catalog_id = CAST(:cid AS uuid) AND system_key = :key"
            ),
            {"cid": catalog_id, "key": sys_key},
        ).fetchone()
        if row:
            return str(row[0])
        new_id = str(uuid.uuid4())
        db.execute(
            text(
                """
                INSERT INTO collections
                    (id, catalog_id, name, source, system_key, parent_id, created_at, updated_at)
                VALUES
                    (CAST(:id AS uuid), CAST(:cid AS uuid), :name, 'system',
                     :key, CAST(:pid AS uuid), NOW(), NOW())
                """
            ),
            {
                "id": new_id,
                "cid": catalog_id,
                "name": name,
                "key": sys_key,
                "pid": people_col_id,
            },
        )
        db.commit()
        return new_id


def _assign_faces_to_person(
    catalog_id: str,
    cluster_label: int,
    labels: np.ndarray,
    face_ids: List[str],
    person_col_id: str,
) -> None:
    """Update face.person_collection_id for all faces in this cluster."""
    from sqlalchemy import text

    cluster_face_ids = [
        face_ids[i] for i, lbl in enumerate(labels) if lbl == cluster_label
    ]
    if not cluster_face_ids:
        return
    with get_db_context() as db:
        db.execute(
            text(
                """
                UPDATE faces SET person_collection_id = CAST(:pid AS uuid)
                WHERE id = ANY(CAST(:ids AS uuid[]))
                """
            ),
            {"pid": person_col_id, "ids": cluster_face_ids},
        )
        db.commit()


def _upsert_image_memberships(
    catalog_id: str, collection_id: str, image_ids: List[str]
) -> int:
    from sqlalchemy import text

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
                    gen_random_uuid(), CAST(:cid AS uuid),
                    unnest(CAST(:ids AS text[])),
                    0, NOW(), 0.75, false, 'system'
                ON CONFLICT (collection_id, image_id) DO NOTHING
                """
            ),
            {"cid": collection_id, "ids": to_insert},
        )
        db.commit()
        return len(to_insert)
