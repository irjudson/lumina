"""Detect faces in catalog images and store embeddings for later clustering.

Uses InsightFace (ArcFace / buffalo_l) with GPU via ONNX Runtime.
The resulting face rows are consumed by the cluster_faces job to build
per-person sub-collections under the People system category.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from ...db.connection import get_db_context
from ..background_jobs import should_stop_job, update_job_status
from ..types import JobContext

logger = logging.getLogger(__name__)

# InsightFace model directory — persistent across container restarts if mounted
MODEL_DIR = os.environ.get("INSIGHTFACE_MODEL_DIR", "/app/models/insightface")
BATCH_SIZE = 50
MIN_DETECTION_SCORE = 0.6  # discard low-confidence detections


def _load_app():
    """Lazily load InsightFace FaceAnalysis, downloading model if needed.

    Tries CUDA first; falls back to CPU if CUDA initialisation fails
    (e.g. cuBLAS resource allocation error when VRAM is exhausted).
    """
    from insightface.app import FaceAnalysis

    os.makedirs(MODEL_DIR, exist_ok=True)

    # Attempt GPU first
    try:
        app = FaceAnalysis(
            name="buffalo_l",
            root=MODEL_DIR,
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        app.prepare(ctx_id=0, det_size=(640, 640))
        logger.info("InsightFace buffalo_l loaded on GPU")
        return app
    except Exception as gpu_err:
        logger.warning(f"GPU initialisation failed ({gpu_err}); falling back to CPU")

    # CPU fallback — ctx_id=-1 tells InsightFace to skip GPU context
    try:
        app = FaceAnalysis(
            name="buffalo_l",
            root=MODEL_DIR,
            providers=["CPUExecutionProvider"],
        )
        app.prepare(ctx_id=-1, det_size=(640, 640))
        logger.info("InsightFace buffalo_l loaded on CPU (GPU unavailable)")
        return app
    except Exception as cpu_err:
        logger.error(f"Failed to load InsightFace on CPU: {cpu_err}")
        raise


def detect_faces_job(ctx: JobContext) -> Dict[str, Any]:
    """Run face detection on all un-processed images in the catalog."""
    catalog_id = ctx.catalog_id
    force = ctx.get("force", False)

    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={"percent": 0, "message": "Loading face detection model"},
    )

    face_app = _load_app()

    # Fetch images that haven't had face detection run (or all if force=True)
    with get_db_context() as db:
        from sqlalchemy import text

        if force:
            rows = db.execute(
                text(
                    """
                    SELECT i.id, i.source_path, i.organized_path
                    FROM images i
                    WHERE i.catalog_id = CAST(:cid AS uuid)
                      AND i.file_type = 'image'
                      AND i.status_id NOT IN ('rejected', 'archived')
                    ORDER BY i.capture_time DESC NULLS LAST
                    """
                ),
                {"cid": catalog_id},
            ).fetchall()
        else:
            # Skip images that already have face rows
            rows = db.execute(
                text(
                    """
                    SELECT i.id, i.source_path, i.organized_path
                    FROM images i
                    WHERE i.catalog_id = CAST(:cid AS uuid)
                      AND i.file_type = 'image'
                      AND i.status_id NOT IN ('rejected', 'archived')
                      AND NOT EXISTS (
                          SELECT 1 FROM faces f WHERE f.image_id = i.id
                      )
                    ORDER BY i.capture_time DESC NULLS LAST
                    """
                ),
                {"cid": catalog_id},
            ).fetchall()

    total = len(rows)
    if total == 0:
        return {"faces_detected": 0, "images_processed": 0, "images_skipped": 0}

    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={"percent": 5, "message": f"Processing {total:,} images"},
    )

    faces_detected = 0
    images_processed = 0
    images_error = 0
    pending_inserts: List[Dict[str, Any]] = []

    for idx, (image_id, source_path, organized_path) in enumerate(rows):
        if should_stop_job(ctx.job_id):
            break

        # Progress update every 50 images
        if idx % BATCH_SIZE == 0:
            percent = 5 + int((idx / total) * 90)
            update_job_status(
                ctx.job_id,
                "PROGRESS",
                progress={
                    "percent": percent,
                    "message": f"Detecting faces {idx:,}/{total:,}",
                },
            )

        img_path = organized_path or source_path
        if not img_path or not Path(img_path).exists():
            continue

        try:
            faces = _detect_in_image(face_app, img_path)
        except Exception as e:
            logger.debug(f"Face detection failed for {img_path}: {e}")
            images_error += 1
            continue

        images_processed += 1
        for face_data in faces:
            face_data["image_id"] = image_id
            face_data["catalog_id"] = catalog_id
            pending_inserts.append(face_data)
            faces_detected += 1

        # Flush batch to DB
        if len(pending_inserts) >= BATCH_SIZE:
            _flush_faces(pending_inserts)
            pending_inserts.clear()

    if pending_inserts:
        _flush_faces(pending_inserts)

    update_job_status(
        ctx.job_id,
        "PROGRESS",
        progress={"percent": 100, "message": "Done"},
    )

    return {
        "faces_detected": faces_detected,
        "images_processed": images_processed,
        "images_error": images_error,
    }


def _detect_in_image(face_app: Any, img_path: str) -> List[Dict[str, Any]]:
    """Run InsightFace on one image, return list of face dicts."""
    import cv2

    img = cv2.imread(img_path)
    if img is None:
        # Try PIL for HEIC and other formats
        from PIL import Image as PILImage

        pil_img = PILImage.open(img_path).convert("RGB")
        img = np.array(pil_img)[:, :, ::-1]  # RGB → BGR for OpenCV

    faces = face_app.get(img)
    results = []
    for face in faces:
        if face.det_score < MIN_DETECTION_SCORE:
            continue
        bbox = face.bbox  # [x1, y1, x2, y2]
        emb: Optional[np.ndarray] = face.embedding  # shape (512,)
        results.append(
            {
                "bbox_x": float(bbox[0]),
                "bbox_y": float(bbox[1]),
                "bbox_w": float(bbox[2] - bbox[0]),
                "bbox_h": float(bbox[3] - bbox[1]),
                "detection_score": float(face.det_score),
                "embedding": emb.tolist() if emb is not None else None,
            }
        )
    return results


def _flush_faces(faces: List[Dict[str, Any]]) -> None:
    """Bulk-insert face rows."""
    from sqlalchemy import text

    with get_db_context() as db:
        for f in faces:
            emb_str = (
                "[" + ",".join(f"{v:.6f}" for v in f["embedding"]) + "]"
                if f["embedding"]
                else None
            )
            db.execute(
                text(
                    """
                    INSERT INTO faces
                        (catalog_id, image_id, bbox_x, bbox_y, bbox_w, bbox_h,
                         detection_score, embedding, detected_at)
                    VALUES
                        (CAST(:cid AS uuid), :img_id,
                         :bx, :by, :bw, :bh, :score,
                         CAST(:emb AS vector), NOW())
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "cid": str(f["catalog_id"]),
                    "img_id": f["image_id"],
                    "bx": f["bbox_x"],
                    "by": f["bbox_y"],
                    "bw": f["bbox_w"],
                    "bh": f["bbox_h"],
                    "score": f["detection_score"],
                    "emb": emb_str,
                },
            )
        db.commit()
