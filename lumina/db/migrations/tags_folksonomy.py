"""Migration: folksonomy tag system — folk_tags, ml_groups, annotation_suggestions, people, routing."""

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

_STATEMENTS = [
    # Folk tags — the user-driven folksonomy annotation primitive
    # Named folk_tags to coexist with the existing ML auto-tags table.
    """
    CREATE TABLE IF NOT EXISTS folk_tags (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        catalog_id  UUID NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
        slug        TEXT NOT NULL,
        label       TEXT NOT NULL,
        parent_id   UUID REFERENCES folk_tags(id) ON DELETE SET NULL,
        notes       TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (catalog_id, slug)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_folk_tags_catalog ON folk_tags (catalog_id)",
    "CREATE INDEX IF NOT EXISTS idx_folk_tags_parent ON folk_tags (parent_id) WHERE parent_id IS NOT NULL",
    # Image <-> Folk tag: confirmed human or ML-confirmed annotations
    """
    CREATE TABLE IF NOT EXISTS folk_image_tags (
        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        image_id     TEXT NOT NULL,
        tag_id       UUID NOT NULL REFERENCES folk_tags(id) ON DELETE CASCADE,
        confidence   FLOAT NOT NULL DEFAULT 1.0,
        source       TEXT NOT NULL DEFAULT 'human',
        model        TEXT,
        annotated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (image_id, tag_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_folk_image_tags_image ON folk_image_tags (image_id)",
    "CREATE INDEX IF NOT EXISTS idx_folk_image_tags_tag ON folk_image_tags (tag_id)",
    # ML Groups — clusters surfaced by ML, pending human naming
    """
    CREATE TABLE IF NOT EXISTS ml_groups (
        id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        catalog_id       UUID NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
        method           TEXT NOT NULL,
        label_hint       TEXT,
        image_count      INT NOT NULL DEFAULT 0,
        sample_image_ids JSONB NOT NULL DEFAULT '[]',
        signals          JSONB NOT NULL DEFAULT '{}',
        status           TEXT NOT NULL DEFAULT 'pending',
        tag_id           UUID REFERENCES folk_tags(id) ON DELETE SET NULL,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        reviewed_at      TIMESTAMPTZ,
        CHECK (status IN ('pending','named','merged','split','deleted','skipped'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ml_groups_catalog_status ON ml_groups (catalog_id, status)",
    # Images in each ML group
    """
    CREATE TABLE IF NOT EXISTS ml_group_images (
        group_id  UUID NOT NULL REFERENCES ml_groups(id) ON DELETE CASCADE,
        image_id  TEXT NOT NULL,
        score     FLOAT,
        PRIMARY KEY (group_id, image_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ml_group_images_image ON ml_group_images (image_id)",
    # ML Annotation Suggestions — ML proposals not yet confirmed by human
    """
    CREATE TABLE IF NOT EXISTS annotation_suggestions (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        image_id            TEXT NOT NULL,
        tag_id              UUID REFERENCES folk_tags(id) ON DELETE CASCADE,
        suggested_label     TEXT,
        confidence          FLOAT NOT NULL,
        empirical_precision FLOAT,
        model               TEXT NOT NULL,
        evidence            JSONB NOT NULL DEFAULT '{}',
        status              TEXT NOT NULL DEFAULT 'pending',
        reviewed_at         TIMESTAMPTZ,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (status IN ('pending','confirmed','rejected','auto_applied'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_suggestions_image ON annotation_suggestions (image_id)",
    "CREATE INDEX IF NOT EXISTS idx_suggestions_status ON annotation_suggestions (status)",
    "CREATE INDEX IF NOT EXISTS idx_suggestions_tag ON annotation_suggestions (tag_id) WHERE tag_id IS NOT NULL",
    # People — structured companion to person folk_tags
    """
    CREATE TABLE IF NOT EXISTS people (
        id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        catalog_id UUID NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
        tag_id     UUID REFERENCES folk_tags(id) ON DELETE SET NULL,
        name       TEXT NOT NULL,
        notes      TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_people_catalog ON people (catalog_id)",
    "CREATE INDEX IF NOT EXISTS idx_people_tag ON people (tag_id) WHERE tag_id IS NOT NULL",
    # Image <-> Person with inferred age
    """
    CREATE TABLE IF NOT EXISTS image_people (
        image_id      TEXT NOT NULL,
        person_id     UUID NOT NULL REFERENCES people(id) ON DELETE CASCADE,
        confidence    FLOAT NOT NULL DEFAULT 1.0,
        source        TEXT NOT NULL DEFAULT 'human',
        inferred_age  FLOAT,
        PRIMARY KEY (image_id, person_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_image_people_person ON image_people (person_id)",
    # Model performance tracking
    """
    CREATE TABLE IF NOT EXISTS model_performance (
        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        model        TEXT NOT NULL,
        task         TEXT NOT NULL,
        precision    FLOAT,
        recall       FLOAT,
        sample_count INT,
        evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    # Learned routing rules
    """
    CREATE TABLE IF NOT EXISTS routing_rules (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        task          TEXT NOT NULL,
        image_context JSONB NOT NULL DEFAULT '{}',
        model         TEXT NOT NULL,
        priority      INT NOT NULL DEFAULT 0,
        source        TEXT NOT NULL DEFAULT 'default',
        created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    # Auto-apply rules — empirical precision gating, not raw model confidence
    """
    CREATE TABLE IF NOT EXISTS auto_apply_rules (
        id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        catalog_id              UUID NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
        tag_id                  UUID REFERENCES folk_tags(id) ON DELETE CASCADE,
        model                   TEXT,
        min_empirical_precision FLOAT NOT NULL,
        granted_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        notes                   TEXT
    )
    """,
]

_DEFAULT_ROUTING_RULES = [
    ("cluster_visual", "clip_hdbscan", 0),
    ("cluster_temporal", "dbscan_geo", 0),
    ("caption", "qwen3-vl", 0),
    ("classify_face", "insightface", 0),
    ("quality_sharp", "laplacian", 0),
]


def upgrade(engine) -> None:
    with engine.connect() as conn:
        for stmt in _STATEMENTS:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception as e:
                logger.warning(f"Migration stmt skipped ({e!r}): {stmt.strip()[:60]}")
                conn.rollback()

    # Seed default routing rules if table is empty
    with engine.connect() as conn:
        try:
            count = conn.execute(text("SELECT COUNT(*) FROM routing_rules")).scalar()
            if count == 0:
                for task, model, priority in _DEFAULT_ROUTING_RULES:
                    conn.execute(
                        text(
                            "INSERT INTO routing_rules (task, model, priority, source)"
                            " VALUES (:task, :model, :priority, 'default')"
                            " ON CONFLICT DO NOTHING"
                        ),
                        {"task": task, "model": model, "priority": priority},
                    )
                conn.commit()
                logger.info("Seeded default routing rules")
        except Exception as e:
            logger.warning(f"Could not seed routing rules: {e}")
            conn.rollback()

    logger.info("tags_folksonomy migration applied")
