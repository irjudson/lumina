"""Migration: add deduplication tables and dhash_16/dhash_32 columns to images."""

from sqlalchemy import text


def upgrade(engine):
    """Apply deduplication schema changes."""
    with engine.begin() as conn:
        # Add multi-resolution hash columns to images
        conn.execute(
            text(
                """
            ALTER TABLE images
            ADD COLUMN IF NOT EXISTS dhash_16 TEXT,
            ADD COLUMN IF NOT EXISTS dhash_32 TEXT
        """
            )
        )

        # duplicate_candidates
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS duplicate_candidates (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                catalog_id UUID NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
                image_id_a VARCHAR NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                image_id_b VARCHAR NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                layer VARCHAR(50) NOT NULL,
                confidence FLOAT NOT NULL,
                verify_carefully BOOLEAN NOT NULL DEFAULT FALSE,
                verify_reason TEXT,
                detection_meta JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                reviewed_at TIMESTAMP,
                CONSTRAINT uq_candidate_pair_layer UNIQUE (image_id_a, image_id_b, layer),
                CONSTRAINT ck_candidate_pair_ordered CHECK (image_id_a < image_id_b),
                CONSTRAINT ck_candidate_layer CHECK (layer IN ('exact','reimport','format_variant','preview','near_duplicate'))
            )
        """
            )
        )
        conn.execute(
            text(
                """
            CREATE INDEX IF NOT EXISTS idx_candidates_catalog
            ON duplicate_candidates(catalog_id, reviewed_at)
        """
            )
        )
        conn.execute(
            text(
                """
            CREATE INDEX IF NOT EXISTS idx_candidates_layer
            ON duplicate_candidates(catalog_id, layer, confidence DESC)
        """
            )
        )

        # duplicate_decisions
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS duplicate_decisions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                candidate_id UUID NOT NULL REFERENCES duplicate_candidates(id) ON DELETE RESTRICT,
                decision VARCHAR(50) NOT NULL,
                primary_id VARCHAR REFERENCES images(id) ON DELETE SET NULL,
                decided_at TIMESTAMP NOT NULL DEFAULT NOW(),
                notes TEXT,
                CONSTRAINT ck_decision_value CHECK (decision IN ('confirmed_duplicate','not_duplicate','deferred'))
            )
        """
            )
        )

        # archived_images
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS archived_images (
                id TEXT PRIMARY KEY,
                catalog_id UUID NOT NULL REFERENCES catalogs(id) ON DELETE RESTRICT,
                source_path TEXT NOT NULL,
                file_type VARCHAR NOT NULL,
                checksum TEXT NOT NULL,
                size_bytes BIGINT,
                dates JSONB NOT NULL DEFAULT '{}',
                metadata JSONB NOT NULL DEFAULT '{}',
                thumbnail_path TEXT,
                dhash TEXT,
                ahash TEXT,
                whash TEXT,
                dhash_16 TEXT,
                dhash_32 TEXT,
                quality_score INTEGER,
                capture_time TIMESTAMP,
                camera_make VARCHAR(255),
                camera_model VARCHAR(255),
                width INTEGER,
                height INTEGER,
                format VARCHAR(20),
                latitude FLOAT,
                longitude FLOAT,
                processing_flags JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMP,
                archived_at TIMESTAMP NOT NULL DEFAULT NOW(),
                archive_reason VARCHAR(50) NOT NULL,
                decision_id UUID NOT NULL REFERENCES duplicate_decisions(id) ON DELETE RESTRICT,
                primary_image_id TEXT NOT NULL,
                original_catalog_id UUID NOT NULL,
                restoration_path TEXT
            )
        """
            )
        )

        # detection_thresholds
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS detection_thresholds (
                catalog_id UUID NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
                layer VARCHAR(50) NOT NULL,
                threshold FLOAT NOT NULL,
                confirmed_count INTEGER NOT NULL DEFAULT 0,
                rejected_count INTEGER NOT NULL DEFAULT 0,
                last_run_threshold FLOAT,
                updated_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (catalog_id, layer)
            )
        """
            )
        )

        # suppression_pairs
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS suppression_pairs (
                id_a TEXT NOT NULL,
                id_b TEXT NOT NULL,
                decision VARCHAR(50) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                PRIMARY KEY (id_a, id_b),
                CONSTRAINT ck_suppression_pair_ordered CHECK (id_a < id_b)
            )
        """
            )
        )


def downgrade(engine):
    """Reverse deduplication schema changes."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS suppression_pairs CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS detection_thresholds CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS archived_images CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS duplicate_decisions CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS duplicate_candidates CASCADE"))
        conn.execute(text("ALTER TABLE images DROP COLUMN IF EXISTS dhash_16"))
        conn.execute(text("ALTER TABLE images DROP COLUMN IF EXISTS dhash_32"))
