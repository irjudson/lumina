"""Migration: add content_class column to images table."""

from sqlalchemy import text


def upgrade(engine):
    """Add content_class to images — idempotent via IF NOT EXISTS."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
            ALTER TABLE images
            ADD COLUMN IF NOT EXISTS content_class VARCHAR(32)
        """
            )
        )
        conn.execute(
            text(
                """
            CREATE INDEX IF NOT EXISTS idx_images_content_class
            ON images (content_class)
        """
            )
        )


def downgrade(engine):
    """Remove content_class from images."""
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS idx_images_content_class"))
        conn.execute(text("ALTER TABLE images DROP COLUMN IF EXISTS content_class"))
