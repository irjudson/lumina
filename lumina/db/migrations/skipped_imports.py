"""Migration: add skipped_imports table."""

from sqlalchemy import text


def upgrade(engine):
    with engine.connect() as conn:
        # Ensure pending_duplicate status exists (needed by near-dedup hash step)
        conn.execute(
            text(
                """
            INSERT INTO image_statuses (id, name, description, created_at)
            VALUES ('pending_duplicate', 'Pending Duplicate',
                    'Near-duplicate detected at hash time, pending review', NOW())
            ON CONFLICT (id) DO NOTHING
        """
            )
        )
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS skipped_imports (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                catalog_id UUID NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
                source_path TEXT NOT NULL,
                checksum TEXT NOT NULL,
                matched_image_id TEXT NOT NULL,
                skipped_at TIMESTAMP NOT NULL DEFAULT NOW(),
                reviewed_at TIMESTAMP,
                overridden BOOLEAN NOT NULL DEFAULT FALSE
            )
        """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_skipped_imports_catalog"
                " ON skipped_imports(catalog_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_skipped_imports_checksum"
                " ON skipped_imports(checksum)"
            )
        )
        conn.commit()


def downgrade(engine):
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS skipped_imports"))
        conn.commit()
