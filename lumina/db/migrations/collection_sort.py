"""Migration: add user_renamed and sort_position to collections."""

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

_STATEMENTS = [
    """
    DO $body$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'collections' AND column_name = 'user_renamed'
        ) THEN
            ALTER TABLE collections ADD COLUMN user_renamed BOOLEAN NOT NULL DEFAULT FALSE;
        END IF;
    END $body$
    """,
    """
    DO $body$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'collections' AND column_name = 'sort_position'
        ) THEN
            ALTER TABLE collections ADD COLUMN sort_position INTEGER;
        END IF;
    END $body$
    """,
    "CREATE INDEX IF NOT EXISTS idx_collections_sort ON collections(parent_id, sort_position NULLS LAST, user_renamed DESC)",
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
    logger.info("collection_sort migration applied")
