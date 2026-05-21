"""Migration: add parent_id to collections for 2-level hierarchy."""

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

_STATEMENTS = [
    "ALTER TABLE collections ADD COLUMN IF NOT EXISTS parent_id UUID REFERENCES collections(id) ON DELETE CASCADE",
    "CREATE INDEX IF NOT EXISTS idx_collections_parent_id ON collections(parent_id) WHERE parent_id IS NOT NULL",
]


def upgrade(engine) -> None:
    with engine.connect() as conn:
        for stmt in _STATEMENTS:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception as e:
                logger.warning(f"Migration stmt skipped ({e}): {stmt[:80]}")
                conn.rollback()

    logger.info("collection_hierarchy migration applied")
