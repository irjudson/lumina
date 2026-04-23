"""Migration: add organized_path column to images table."""

from sqlalchemy import text


def upgrade(engine):
    """Add organized_path to images — idempotent via IF NOT EXISTS."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
            ALTER TABLE images
            ADD COLUMN IF NOT EXISTS organized_path TEXT
        """
            )
        )


def downgrade(engine):
    """Remove organized_path from images."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE images DROP COLUMN IF EXISTS organized_path"))
