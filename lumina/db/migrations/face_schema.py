"""Migration: create faces table for face detection results."""

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS faces (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        catalog_id UUID NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
        image_id TEXT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
        bbox_x FLOAT NOT NULL,
        bbox_y FLOAT NOT NULL,
        bbox_w FLOAT NOT NULL,
        bbox_h FLOAT NOT NULL,
        detection_score FLOAT NOT NULL,
        embedding vector(512),
        person_collection_id UUID REFERENCES collections(id) ON DELETE SET NULL,
        detected_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_faces_catalog_id ON faces(catalog_id)",
    "CREATE INDEX IF NOT EXISTS idx_faces_image_id ON faces(image_id)",
    "CREATE INDEX IF NOT EXISTS idx_faces_person ON faces(person_collection_id) WHERE person_collection_id IS NOT NULL",
]


def upgrade(engine) -> None:
    with engine.connect() as conn:
        for stmt in _STATEMENTS:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception as e:
                logger.warning(f"Migration stmt skipped ({e}): {stmt[:60].strip()}")
                conn.rollback()

    logger.info("face_schema migration applied")
