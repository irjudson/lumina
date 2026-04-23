"""Migration: add events and event_images tables for time-space event detection."""

from sqlalchemy import text


def upgrade(engine):
    """Apply events schema (idempotent)."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                catalog_id UUID NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
                name VARCHAR(255),
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP NOT NULL,
                duration_minutes INTEGER NOT NULL,
                image_count INTEGER NOT NULL,
                center_lat DOUBLE PRECISION,
                center_lon DOUBLE PRECISION,
                radius_km DOUBLE PRECISION,
                score DOUBLE PRECISION NOT NULL DEFAULT 0,
                detected_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """
            )
        )

        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS event_images (
                event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                image_id VARCHAR NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                PRIMARY KEY (event_id, image_id)
            )
        """
            )
        )

        conn.execute(
            text(
                """
            CREATE INDEX IF NOT EXISTS idx_events_catalog_score
                ON events(catalog_id, score DESC)
        """
            )
        )

        conn.execute(
            text(
                """
            CREATE INDEX IF NOT EXISTS idx_event_images_image
                ON event_images(image_id)
        """
            )
        )
