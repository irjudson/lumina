"""Migration: add backup_destinations JSONB column to catalogs."""

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

_STATEMENTS = [
    "ALTER TABLE catalogs ADD COLUMN IF NOT EXISTS backup_destinations JSONB DEFAULT '[]'::jsonb",
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

    logger.info("backup_destinations migration applied")
