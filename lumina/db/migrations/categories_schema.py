"""Migration: extend collections/collection_images for system categories.

Adds:
- collections.source          VARCHAR(16) DEFAULT 'user'
- collections.system_key      TEXT UNIQUE (null for user collections)
- collection_images.confidence FLOAT DEFAULT 1.0
- collection_images.confirmed  BOOLEAN DEFAULT TRUE
- collection_images.source     VARCHAR(16) DEFAULT 'user'
"""

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

_CHECKS = [
    (
        "collections",
        "source",
        "SELECT 1 FROM information_schema.columns WHERE table_name='collections' AND column_name='source'",
    ),
    (
        "collections",
        "system_key",
        "SELECT 1 FROM information_schema.columns WHERE table_name='collections' AND column_name='system_key'",
    ),
    (
        "collection_images",
        "confidence",
        "SELECT 1 FROM information_schema.columns WHERE table_name='collection_images' AND column_name='confidence'",
    ),
    (
        "collection_images",
        "confirmed",
        "SELECT 1 FROM information_schema.columns WHERE table_name='collection_images' AND column_name='confirmed'",
    ),
    (
        "collection_images",
        "source",
        "SELECT 1 FROM information_schema.columns WHERE table_name='collection_images' AND column_name='source'",
    ),
]

_STATEMENTS = [
    "ALTER TABLE collections ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'user'",
    "ALTER TABLE collections ADD COLUMN IF NOT EXISTS system_key TEXT",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_collections_system_key ON collections(catalog_id, system_key) WHERE system_key IS NOT NULL",
    "ALTER TABLE collection_images ADD COLUMN IF NOT EXISTS confidence FLOAT NOT NULL DEFAULT 1.0",
    "ALTER TABLE collection_images ADD COLUMN IF NOT EXISTS confirmed BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE collection_images ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'user'",
]


def upgrade(engine) -> None:
    with engine.connect() as conn:
        for stmt in _STATEMENTS:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception as e:
                logger.warning(f"Migration stmt skipped ({e}): {stmt[:60]}")
                conn.rollback()

    logger.info("categories_schema migration applied")
