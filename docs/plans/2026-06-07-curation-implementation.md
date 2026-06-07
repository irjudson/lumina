# Curation System — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Implement Phase 1 of the curation system — folksonomy tag model, ML group discovery pipeline, question-first home screen, and curate mode — replacing the existing pre-defined collection hierarchy.

**Architecture:** New `tags`/`ml_groups` schema layered on top of existing `collections` table (which stays for backward compat during transition). Existing face person-collections and travel collections migrate to tags. Empty system collections deleted. Backend API + Vue frontend updated.

**Tech Stack:** FastAPI + PostgreSQL, SQLAlchemy migrations (Python, idempotent), Vue 3 + Pinia + TypeScript + TailwindCSS, Ollama at `http://ollama:11434`, CLIP + FAISS local.

**Key files to know:**
- `lumina/db/models.py` — SQLAlchemy models (Base is declarative_base)
- `lumina/db/connection.py` — `init_db()` calls all migrations; `SYSTEM_COLLECTIONS` list seeded at startup
- `lumina/db/migrations/` — Python migration files with `upgrade(engine)`
- `lumina/api/routers/catalogs.py` — main catalog router (~2000 lines)
- `lumina/api/routers/__init__.py` — router registration
- `lumina/jobs/definitions/` — background job definitions
- `lumina/jobs/types.py` — `JobType` enum
- `lumina/jobs/definitions/__init__.py` — job registry
- `src/stores/` — Pinia stores (collections.ts, library.ts)
- `src/views/` — top-level views (LibraryView.vue, TriageView.vue, ImportView.vue)
- `src/components/library/NavigationSidebar.vue` — left panel
- `src/router/index.ts` — Vue Router
- `src/layouts/LibraryLayout.vue` — 3-panel shell

**Build:** `cd /home/irjudson/Projects/lumina && npm run build` (from project root). Static assets go to `lumina/web/static/` (gittracked). `src/` is gitignored.

---

## Task 1: Schema Migration

**Files:**
- Create: `lumina/db/migrations/tags_folksonomy.py`
- Modify: `lumina/db/connection.py` (register migration in `init_db()`)

**Step 1: Write the migration**

```python
# lumina/db/migrations/tags_folksonomy.py
"""Migration: folksonomy tag system — tags, ml_groups, annotation_suggestions, people, routing."""

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

_STATEMENTS = [
    # Tags — the universal annotation primitive
    """
    CREATE TABLE IF NOT EXISTS tags (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        catalog_id  UUID NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
        slug        TEXT NOT NULL,
        label       TEXT NOT NULL,
        parent_id   UUID REFERENCES tags(id) ON DELETE SET NULL,
        notes       TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (catalog_id, slug)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tags_catalog ON tags (catalog_id)",
    "CREATE INDEX IF NOT EXISTS idx_tags_parent ON tags (parent_id) WHERE parent_id IS NOT NULL",

    # Image ↔ Tag: confirmed annotations
    """
    CREATE TABLE IF NOT EXISTS image_tags (
        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        image_id     TEXT NOT NULL,
        tag_id       UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        confidence   FLOAT NOT NULL DEFAULT 1.0,
        source       TEXT NOT NULL DEFAULT 'human',
        model        TEXT,
        annotated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (image_id, tag_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_image_tags_image ON image_tags (image_id)",
    "CREATE INDEX IF NOT EXISTS idx_image_tags_tag ON image_tags (tag_id)",

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
        tag_id           UUID REFERENCES tags(id) ON DELETE SET NULL,
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

    # ML Annotation Suggestions — proposals not yet confirmed
    """
    CREATE TABLE IF NOT EXISTS annotation_suggestions (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        image_id            TEXT NOT NULL,
        tag_id              UUID REFERENCES tags(id) ON DELETE CASCADE,
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

    # People — structured companion to person tags
    """
    CREATE TABLE IF NOT EXISTS people (
        id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        catalog_id UUID NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
        tag_id     UUID REFERENCES tags(id) ON DELETE SET NULL,
        name       TEXT NOT NULL,
        notes      TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_people_catalog ON people (catalog_id)",
    "CREATE INDEX IF NOT EXISTS idx_people_tag ON people (tag_id) WHERE tag_id IS NOT NULL",

    # Image ↔ Person with inferred age
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

    # Auto-apply rules (empirical precision gating, not raw confidence)
    """
    CREATE TABLE IF NOT EXISTS auto_apply_rules (
        id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        catalog_id              UUID NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
        tag_id                  UUID REFERENCES tags(id) ON DELETE CASCADE,
        model                   TEXT,
        min_empirical_precision FLOAT NOT NULL,
        granted_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        notes                   TEXT
    )
    """,
]

_DEFAULT_ROUTING_RULES = [
    ("cluster_visual",  "clip_hdbscan",  0),
    ("cluster_temporal","dbscan_geo",     0),
    ("caption",         "qwen3-vl",       0),
    ("classify_face",   "insightface",    0),
    ("quality_sharp",   "laplacian",      0),
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

    logger.info("tags_folksonomy migration applied")
```

**Step 2: Register in init_db()**

In `lumina/db/connection.py`, after the existing migration calls (~line 185), add:

```python
    from .migrations.tags_folksonomy import upgrade as upgrade_tags
    upgrade_tags(engine)
    logger.info("Tags folksonomy migration applied")
```

**Step 3: Run tests**

```bash
cd /home/irjudson/Projects/lumina
docker compose exec api python -c "
from lumina.db.connection import init_db
init_db()
print('Migration OK')
"
```

Expected: `Migration OK` with no errors.

**Step 4: Verify tables exist**

```bash
docker compose exec db psql -U lumina -d lumina -c "\dt tags ml_groups ml_group_images annotation_suggestions people image_people model_performance routing_rules auto_apply_rules"
```

Expected: all 9 tables listed.

**Step 5: Commit**

```bash
git add lumina/db/migrations/tags_folksonomy.py lumina/db/connection.py
git commit -m "feat: tags folksonomy schema migration — tags, ml_groups, suggestions, people, routing"
```

---

## Task 2: Data Migration — Existing Collections → Tags

**Files:**
- Create: `lumina/db/migrations/collections_to_tags.py`
- Modify: `lumina/db/connection.py` (register + remove SYSTEM_COLLECTIONS seeding)

**Step 1: Understand current face data**

```bash
docker compose exec db psql -U lumina -d lumina -c "
SELECT c.system_key, c.name, COUNT(ci.image_id) as img_count
FROM collections c
LEFT JOIN collection_images ci ON ci.collection_id = c.id
WHERE c.source = 'system'
GROUP BY c.system_key, c.name
ORDER BY img_count DESC;
"
```

**Step 2: Write the migration**

```python
# lumina/db/migrations/collections_to_tags.py
"""Migrate face person-collections and travel collection to tags. Delete empty system collections."""

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

EMPTY_SYSTEM_KEYS = {"family_personal", "work_professional", "archival", "projects", "last_import"}


def upgrade(engine) -> None:
    with engine.connect() as conn:
        # 1. Migrate travel collection and its children to tag hierarchy
        _migrate_travel(conn)

        # 2. Migrate face person-collections to people + tags
        _migrate_people(conn)

        # 3. Delete empty system collections
        _delete_empty_collections(conn)

        conn.commit()
    logger.info("collections_to_tags migration applied")


def _migrate_travel(conn) -> None:
    """Travel collection → tag 'travel', sub-collections → child tags."""
    catalogs = conn.execute(text("SELECT id FROM catalogs")).fetchall()
    for (catalog_id,) in catalogs:
        # Get travel parent collection
        travel = conn.execute(
            text(
                "SELECT id, name FROM collections"
                " WHERE catalog_id = :cid AND system_key = 'travel' LIMIT 1"
            ),
            {"cid": str(catalog_id)},
        ).first()
        if not travel:
            continue

        # Create travel tag
        travel_tag_id = conn.execute(
            text(
                "INSERT INTO tags (catalog_id, slug, label)"
                " VALUES (CAST(:cid AS uuid), 'travel', 'Travel')"
                " ON CONFLICT (catalog_id, slug) DO UPDATE SET label = EXCLUDED.label"
                " RETURNING id"
            ),
            {"cid": str(catalog_id)},
        ).scalar()

        # Migrate travel child collections (geographic sub-collections)
        children = conn.execute(
            text(
                "SELECT id, name FROM collections"
                " WHERE catalog_id = :cid AND parent_id = CAST(:pid AS uuid)"
            ),
            {"cid": str(catalog_id), "pid": str(travel[0])},
        ).fetchall()

        for child_id, child_name in children:
            slug = child_name.lower().replace(" ", "_").replace("/", "_")[:80]
            child_tag_id = conn.execute(
                text(
                    "INSERT INTO tags (catalog_id, slug, label, parent_id)"
                    " VALUES (CAST(:cid AS uuid), :slug, :label, CAST(:parent AS uuid))"
                    " ON CONFLICT (catalog_id, slug) DO UPDATE SET label = EXCLUDED.label"
                    " RETURNING id"
                ),
                {"cid": str(catalog_id), "slug": slug, "label": child_name, "parent": str(travel_tag_id)},
            ).scalar()

            # Migrate images
            images = conn.execute(
                text("SELECT image_id FROM collection_images WHERE collection_id = CAST(:cid AS uuid)"),
                {"cid": str(child_id)},
            ).fetchall()
            for (image_id,) in images:
                conn.execute(
                    text(
                        "INSERT INTO image_tags (image_id, tag_id, source)"
                        " VALUES (:iid, CAST(:tid AS uuid), 'migration')"
                        " ON CONFLICT DO NOTHING"
                    ),
                    {"iid": image_id, "tid": str(child_tag_id)},
                )

        logger.info(f"Migrated travel collection for catalog {catalog_id}: {len(children)} sub-tags")


def _migrate_people(conn) -> None:
    """Face person-collections → tags + people records + image_people links."""
    catalogs = conn.execute(text("SELECT id FROM catalogs")).fetchall()
    for (catalog_id,) in catalogs:
        # Get people parent collection
        people_coll = conn.execute(
            text(
                "SELECT id FROM collections"
                " WHERE catalog_id = :cid AND system_key = 'people' LIMIT 1"
            ),
            {"cid": str(catalog_id)},
        ).first()
        if not people_coll:
            continue

        # Get person sub-collections (children of people collection)
        persons = conn.execute(
            text(
                "SELECT id, name FROM collections"
                " WHERE catalog_id = :cid AND parent_id = CAST(:pid AS uuid)"
            ),
            {"cid": str(catalog_id), "pid": str(people_coll[0])},
        ).fetchall()

        for person_coll_id, person_name in persons:
            slug = "person_" + person_name.lower().replace(" ", "_")[:60]
            tag_id = conn.execute(
                text(
                    "INSERT INTO tags (catalog_id, slug, label)"
                    " VALUES (CAST(:cid AS uuid), :slug, :label)"
                    " ON CONFLICT (catalog_id, slug) DO UPDATE SET label = EXCLUDED.label"
                    " RETURNING id"
                ),
                {"cid": str(catalog_id), "slug": slug, "label": person_name},
            ).scalar()

            person_id = conn.execute(
                text(
                    "INSERT INTO people (catalog_id, tag_id, name)"
                    " VALUES (CAST(:cid AS uuid), CAST(:tid AS uuid), :name)"
                    " ON CONFLICT DO NOTHING RETURNING id"
                ),
                {"cid": str(catalog_id), "tid": str(tag_id), "name": person_name},
            ).scalar()

            if not person_id:
                person_id = conn.execute(
                    text("SELECT id FROM people WHERE catalog_id = CAST(:cid AS uuid) AND name = :name LIMIT 1"),
                    {"cid": str(catalog_id), "name": person_name},
                ).scalar()

            images = conn.execute(
                text("SELECT image_id FROM collection_images WHERE collection_id = CAST(:cid AS uuid)"),
                {"cid": str(person_coll_id)},
            ).fetchall()
            for (image_id,) in images:
                conn.execute(
                    text(
                        "INSERT INTO image_tags (image_id, tag_id, source)"
                        " VALUES (:iid, CAST(:tid AS uuid), 'migration')"
                        " ON CONFLICT DO NOTHING"
                    ),
                    {"iid": image_id, "tid": str(tag_id)},
                )
                if person_id:
                    conn.execute(
                        text(
                            "INSERT INTO image_people (image_id, person_id, source)"
                            " VALUES (:iid, CAST(:pid AS uuid), 'migration')"
                            " ON CONFLICT DO NOTHING"
                        ),
                        {"iid": image_id, "pid": str(person_id)},
                    )

        logger.info(f"Migrated {len(persons)} person collections for catalog {catalog_id}")


def _delete_empty_collections(conn) -> None:
    """Delete the pre-defined system collections that were never used."""
    deleted = conn.execute(
        text(
            "DELETE FROM collections WHERE system_key = ANY(:keys) RETURNING system_key"
        ),
        {"keys": list(EMPTY_SYSTEM_KEYS)},
    ).fetchall()
    logger.info(f"Deleted empty system collections: {[r[0] for r in deleted]}")
```

**Step 3: Register in init_db() and remove SYSTEM_COLLECTIONS seeding**

In `lumina/db/connection.py`:

a) After the tags_folksonomy upgrade call, add:
```python
    from .migrations.collections_to_tags import upgrade as upgrade_collections_to_tags
    upgrade_collections_to_tags(engine)
    logger.info("Collections to tags migration applied")
```

b) In `_seed_system_collections()`, replace the entire function body with:
```python
def _seed_system_collections(db: Session) -> None:
    """No-op: system collections replaced by folksonomy tags."""
    pass
```

**Step 4: Run and verify**

```bash
docker compose exec api python -c "
from lumina.db.connection import init_db
init_db()
print('Migration OK')
"
```

```bash
docker compose exec db psql -U lumina -d lumina -c "
SELECT label, (SELECT COUNT(*) FROM image_tags it WHERE it.tag_id = t.id) as img_count
FROM tags t ORDER BY img_count DESC LIMIT 20;
"
```

Expected: travel sub-tags and person tags with non-zero image counts.

**Step 5: Commit**

```bash
git add lumina/db/migrations/collections_to_tags.py lumina/db/connection.py
git commit -m "feat: migrate face/travel collections to tags, delete empty system collections"
```

---

## Task 3: Tag API Endpoints

**Files:**
- Create: `lumina/api/routers/tags.py`
- Modify: `lumina/api/routers/__init__.py` (register router)

**Step 1: Write failing tests**

```python
# tests/api/test_tags.py
import pytest
from fastapi.testclient import TestClient


def test_list_tags_empty(client, catalog_id):
    resp = client.get(f"/catalogs/{catalog_id}/tags/")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_and_get_tag(client, catalog_id):
    resp = client.post(f"/catalogs/{catalog_id}/tags/", json={"label": "Work"})
    assert resp.status_code == 201
    tag = resp.json()
    assert tag["label"] == "Work"
    assert tag["slug"] == "work"

    resp2 = client.get(f"/catalogs/{catalog_id}/tags/")
    assert any(t["id"] == tag["id"] for t in resp2.json())


def test_create_child_tag(client, catalog_id):
    parent = client.post(f"/catalogs/{catalog_id}/tags/", json={"label": "Work"}).json()
    child = client.post(
        f"/catalogs/{catalog_id}/tags/",
        json={"label": "Conference", "parent_id": parent["id"]},
    ).json()
    assert child["parent_id"] == parent["id"]


def test_bulk_tag_images(client, catalog_id, image_ids):
    tag = client.post(f"/catalogs/{catalog_id}/tags/", json={"label": "Test"}).json()
    resp = client.post(
        f"/catalogs/{catalog_id}/images/tag/",
        json={"image_ids": image_ids[:3], "tag_id": tag["id"]},
    )
    assert resp.status_code == 200
    assert resp.json()["tagged"] == 3


def test_delete_tag(client, catalog_id):
    tag = client.post(f"/catalogs/{catalog_id}/tags/", json={"label": "Temp"}).json()
    resp = client.delete(f"/catalogs/{catalog_id}/tags/{tag['id']}/")
    assert resp.status_code == 204
```

**Step 2: Run tests to verify they fail**

```bash
cd /home/irjudson/Projects/lumina
python -m pytest tests/api/test_tags.py -v 2>&1 | head -30
```

Expected: ERRORS (router doesn't exist yet).

**Step 3: Implement the router**

```python
# lumina/api/routers/tags.py
"""Tag (folksonomy) API endpoints."""

import re
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from lumina.db import get_db_context

router = APIRouter(prefix="/catalogs/{catalog_id}", tags=["tags"])


def _slugify(label: str) -> str:
    slug = label.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug[:80].strip("_") or "tag"


class TagCreate(BaseModel):
    label: str
    parent_id: Optional[str] = None
    notes: Optional[str] = None


class TagUpdate(BaseModel):
    label: Optional[str] = None
    parent_id: Optional[str] = None
    notes: Optional[str] = None


class BulkTagRequest(BaseModel):
    image_ids: List[str]
    tag_id: str


@router.get("/tags/")
def list_tags(catalog_id: str):
    """Return all tags for a catalog as a flat list (client builds tree)."""
    with get_db_context() as db:
        rows = db.execute(
            sa_text(
                "SELECT id, slug, label, parent_id, notes, created_at,"
                " (SELECT COUNT(*) FROM image_tags it WHERE it.tag_id = t.id) AS image_count"
                " FROM tags t WHERE catalog_id = CAST(:cid AS uuid)"
                " ORDER BY label"
            ),
            {"cid": catalog_id},
        ).fetchall()
    return [
        {
            "id": str(r[0]),
            "slug": r[1],
            "label": r[2],
            "parent_id": str(r[3]) if r[3] else None,
            "notes": r[4],
            "created_at": r[5].isoformat() if r[5] else None,
            "image_count": r[6],
        }
        for r in rows
    ]


@router.post("/tags/", status_code=201)
def create_tag(catalog_id: str, body: TagCreate):
    slug = _slugify(body.label)
    tag_id = str(uuid.uuid4())
    with get_db_context() as db:
        # Ensure unique slug within catalog
        existing = db.execute(
            sa_text("SELECT id FROM tags WHERE catalog_id = CAST(:cid AS uuid) AND slug = :slug"),
            {"cid": catalog_id, "slug": slug},
        ).first()
        if existing:
            # Append suffix to make unique
            slug = f"{slug}_{tag_id[:4]}"

        db.execute(
            sa_text(
                "INSERT INTO tags (id, catalog_id, slug, label, parent_id, notes)"
                " VALUES (CAST(:id AS uuid), CAST(:cid AS uuid), :slug, :label,"
                " CAST(:parent AS uuid), :notes)"
            ),
            {
                "id": tag_id,
                "cid": catalog_id,
                "slug": slug,
                "label": body.label,
                "parent": body.parent_id,
                "notes": body.notes,
            },
        )
        db.commit()
    return {"id": tag_id, "slug": slug, "label": body.label,
            "parent_id": body.parent_id, "notes": body.notes, "image_count": 0}


@router.patch("/tags/{tag_id}/")
def update_tag(catalog_id: str, tag_id: str, body: TagUpdate):
    with get_db_context() as db:
        existing = db.execute(
            sa_text("SELECT id FROM tags WHERE id = CAST(:id AS uuid) AND catalog_id = CAST(:cid AS uuid)"),
            {"id": tag_id, "cid": catalog_id},
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Tag not found")

        updates = {}
        if body.label is not None:
            updates["label"] = body.label
        if body.parent_id is not None:
            updates["parent_id"] = body.parent_id
        if body.notes is not None:
            updates["notes"] = body.notes

        if updates:
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            db.execute(
                sa_text(f"UPDATE tags SET {set_clause} WHERE id = CAST(:id AS uuid)"),
                {**updates, "id": tag_id},
            )
            db.commit()
    return {"id": tag_id, **updates}


@router.delete("/tags/{tag_id}/", status_code=204)
def delete_tag(catalog_id: str, tag_id: str):
    with get_db_context() as db:
        db.execute(
            sa_text("DELETE FROM tags WHERE id = CAST(:id AS uuid) AND catalog_id = CAST(:cid AS uuid)"),
            {"id": tag_id, "cid": catalog_id},
        )
        db.commit()


@router.post("/images/tag/")
def bulk_tag_images(catalog_id: str, body: BulkTagRequest):
    """Add a tag to multiple images at once."""
    with get_db_context() as db:
        tag_exists = db.execute(
            sa_text("SELECT id FROM tags WHERE id = CAST(:id AS uuid) AND catalog_id = CAST(:cid AS uuid)"),
            {"id": body.tag_id, "cid": catalog_id},
        ).first()
        if not tag_exists:
            raise HTTPException(status_code=404, detail="Tag not found")

        tagged = 0
        now = datetime.utcnow().isoformat()
        for image_id in body.image_ids:
            db.execute(
                sa_text(
                    "INSERT INTO image_tags (image_id, tag_id, source, annotated_at)"
                    " VALUES (:iid, CAST(:tid AS uuid), 'human', :now)"
                    " ON CONFLICT DO NOTHING"
                ),
                {"iid": image_id, "tid": body.tag_id, "now": now},
            )
            tagged += 1
        db.commit()
    return {"tagged": tagged}


@router.delete("/images/tag/")
def bulk_untag_images(catalog_id: str, body: BulkTagRequest):
    """Remove a tag from multiple images."""
    with get_db_context() as db:
        untagged = 0
        for image_id in body.image_ids:
            result = db.execute(
                sa_text(
                    "DELETE FROM image_tags WHERE image_id = :iid AND tag_id = CAST(:tid AS uuid)"
                ),
                {"iid": image_id, "tid": body.tag_id},
            )
            untagged += result.rowcount
        db.commit()
    return {"untagged": untagged}
```

**Step 4: Register the router**

In `lumina/api/routers/__init__.py`, add:
```python
from .tags import router as tags_router
# ... in the list of routers passed to app.include_router:
app.include_router(tags_router)
```

(Check the exact registration pattern in the existing `__init__.py` and follow it.)

**Step 5: Run tests**

```bash
python -m pytest tests/api/test_tags.py -v
```

Expected: all tests pass.

**Step 6: Manual smoke test**

```bash
# Get catalog ID first
CATALOG_ID=$(docker compose exec db psql -U lumina -d lumina -t -c "SELECT id FROM catalogs LIMIT 1" | tr -d ' ')

# Create a tag
curl -s -X POST "http://localhost:8000/catalogs/$CATALOG_ID/tags/" \
  -H "Content-Type: application/json" \
  -d '{"label": "Family Archive"}' | python3 -m json.tool

# List tags (should include migrated travel + person tags)
curl -s "http://localhost:8000/catalogs/$CATALOG_ID/tags/" | python3 -m json.tool | head -40
```

**Step 7: Commit**

```bash
git add lumina/api/routers/tags.py lumina/api/routers/__init__.py tests/api/test_tags.py
git commit -m "feat: tag CRUD API — create, list, update, delete, bulk tag/untag images"
```

---

## Task 4: ML Groups API

**Files:**
- Modify: `lumina/api/routers/tags.py` (add ml_groups endpoints)

**Step 1: Write failing tests**

```python
# tests/api/test_ml_groups.py
def test_list_ml_groups_empty(client, catalog_id):
    resp = client.get(f"/catalogs/{catalog_id}/ml-groups/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_name_ml_group(client, catalog_id, ml_group_id):
    resp = client.post(
        f"/catalogs/{catalog_id}/ml-groups/{ml_group_id}/name/",
        json={"label": "Family Scans"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tag"]["label"] == "Family Scans"
    assert data["group"]["status"] == "named"


def test_skip_ml_group(client, catalog_id, ml_group_id):
    resp = client.post(f"/catalogs/{catalog_id}/ml-groups/{ml_group_id}/skip/")
    assert resp.status_code == 200


def test_delete_ml_group(client, catalog_id, ml_group_id):
    resp = client.post(f"/catalogs/{catalog_id}/ml-groups/{ml_group_id}/delete/")
    assert resp.status_code == 200
    # Should not appear in pending list
    groups = client.get(f"/catalogs/{catalog_id}/ml-groups/").json()
    assert not any(g["id"] == ml_group_id for g in groups)
```

**Step 2: Implement in tags.py**

Add to `lumina/api/routers/tags.py`:

```python
class NameGroupRequest(BaseModel):
    label: str
    parent_id: Optional[str] = None


@router.get("/ml-groups/")
def list_ml_groups(catalog_id: str, status: str = "pending"):
    with get_db_context() as db:
        rows = db.execute(
            sa_text(
                "SELECT id, method, label_hint, image_count, sample_image_ids, signals, status, created_at"
                " FROM ml_groups WHERE catalog_id = CAST(:cid AS uuid) AND status = :status"
                " ORDER BY image_count DESC"
            ),
            {"cid": catalog_id, "status": status},
        ).fetchall()
    return [
        {
            "id": str(r[0]),
            "method": r[1],
            "label_hint": r[2],
            "image_count": r[3],
            "sample_image_ids": r[4],
            "signals": r[5],
            "status": r[6],
            "created_at": r[7].isoformat() if r[7] else None,
        }
        for r in rows
    ]


@router.post("/ml-groups/{group_id}/name/")
def name_ml_group(catalog_id: str, group_id: str, body: NameGroupRequest):
    """Name an ML group — creates a tag and annotates all member images."""
    slug = _slugify(body.label)
    tag_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    with get_db_context() as db:
        group = db.execute(
            sa_text("SELECT id, image_count FROM ml_groups WHERE id = CAST(:id AS uuid) AND catalog_id = CAST(:cid AS uuid)"),
            {"id": group_id, "cid": catalog_id},
        ).first()
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")

        # Create tag
        db.execute(
            sa_text(
                "INSERT INTO tags (id, catalog_id, slug, label, parent_id)"
                " VALUES (CAST(:id AS uuid), CAST(:cid AS uuid), :slug, :label, CAST(:parent AS uuid))"
                " ON CONFLICT (catalog_id, slug) DO UPDATE SET label = EXCLUDED.label"
            ),
            {"id": tag_id, "cid": catalog_id, "slug": slug, "label": body.label, "parent": body.parent_id},
        )

        # Annotate all images in the group
        images = db.execute(
            sa_text("SELECT image_id FROM ml_group_images WHERE group_id = CAST(:gid AS uuid)"),
            {"gid": group_id},
        ).fetchall()
        for (image_id,) in images:
            db.execute(
                sa_text(
                    "INSERT INTO image_tags (image_id, tag_id, source, annotated_at)"
                    " VALUES (:iid, CAST(:tid AS uuid), 'ml_confirmed', :now)"
                    " ON CONFLICT DO NOTHING"
                ),
                {"iid": image_id, "tid": tag_id, "now": now},
            )

        # Mark group as named
        db.execute(
            sa_text(
                "UPDATE ml_groups SET status = 'named', tag_id = CAST(:tid AS uuid), reviewed_at = :now"
                " WHERE id = CAST(:gid AS uuid)"
            ),
            {"tid": tag_id, "now": now, "gid": group_id},
        )
        db.commit()

    return {
        "tag": {"id": tag_id, "slug": slug, "label": body.label, "image_count": len(images)},
        "group": {"id": group_id, "status": "named"},
    }


@router.post("/ml-groups/{group_id}/skip/")
def skip_ml_group(catalog_id: str, group_id: str):
    now = datetime.utcnow().isoformat()
    with get_db_context() as db:
        db.execute(
            sa_text("UPDATE ml_groups SET status = 'skipped', reviewed_at = :now WHERE id = CAST(:id AS uuid) AND catalog_id = CAST(:cid AS uuid)"),
            {"now": now, "id": group_id, "cid": catalog_id},
        )
        db.commit()
    return {"status": "skipped"}


@router.post("/ml-groups/{group_id}/delete/")
def delete_ml_group(catalog_id: str, group_id: str):
    now = datetime.utcnow().isoformat()
    with get_db_context() as db:
        db.execute(
            sa_text("UPDATE ml_groups SET status = 'deleted', reviewed_at = :now WHERE id = CAST(:id AS uuid) AND catalog_id = CAST(:cid AS uuid)"),
            {"now": now, "id": group_id, "cid": catalog_id},
        )
        db.commit()
    return {"status": "deleted"}


@router.post("/ml-groups/{group_id}/merge/")
def merge_ml_group(catalog_id: str, group_id: str, body: dict):
    """Merge this group's images into an existing tag."""
    target_tag_id = body.get("tag_id")
    if not target_tag_id:
        raise HTTPException(status_code=400, detail="tag_id required")
    now = datetime.utcnow().isoformat()
    with get_db_context() as db:
        images = db.execute(
            sa_text("SELECT image_id FROM ml_group_images WHERE group_id = CAST(:gid AS uuid)"),
            {"gid": group_id},
        ).fetchall()
        for (image_id,) in images:
            db.execute(
                sa_text(
                    "INSERT INTO image_tags (image_id, tag_id, source, annotated_at)"
                    " VALUES (:iid, CAST(:tid AS uuid), 'ml_confirmed', :now)"
                    " ON CONFLICT DO NOTHING"
                ),
                {"iid": image_id, "tid": target_tag_id, "now": now},
            )
        db.execute(
            sa_text("UPDATE ml_groups SET status = 'merged', reviewed_at = :now WHERE id = CAST(:id AS uuid)"),
            {"now": now, "id": group_id},
        )
        db.commit()
    return {"merged": len(images), "into_tag_id": target_tag_id}
```

**Step 3: Run tests**

```bash
python -m pytest tests/api/test_ml_groups.py -v
```

**Step 4: Commit**

```bash
git add lumina/api/routers/tags.py tests/api/test_ml_groups.py
git commit -m "feat: ml-groups API — list, name, skip, delete, merge"
```

---

## Task 5: Home Screen API

**Files:**
- Modify: `lumina/api/routers/tags.py` (add home endpoint)
- Modify: `lumina/api/routers/catalogs.py` (add CLIP text search endpoint)

**Step 1: Write test**

```python
# tests/api/test_home.py
def test_home_structure(client, catalog_id):
    resp = client.get(f"/catalogs/{catalog_id}/home/")
    assert resp.status_code == 200
    data = resp.json()
    assert "needs_attention" in data
    assert "recent_tags" in data
```

**Step 2: Implement**

Add to `lumina/api/routers/tags.py`:

```python
@router.get("/home/")
def home_screen(catalog_id: str):
    """Home screen data — what needs attention and recent activity."""
    with get_db_context() as db:
        # Pending ML groups (unnamed clusters)
        pending_groups = db.execute(
            sa_text(
                "SELECT COUNT(*), COALESCE(SUM(image_count), 0)"
                " FROM ml_groups WHERE catalog_id = CAST(:cid AS uuid) AND status = 'pending'"
            ),
            {"cid": catalog_id},
        ).first()

        # Images with no tags (untagged coverage gap)
        untagged_count = db.execute(
            sa_text(
                "SELECT COUNT(*) FROM images i"
                " WHERE i.catalog_id = CAST(:cid AS uuid)"
                " AND NOT EXISTS (SELECT 1 FROM image_tags it WHERE it.image_id = i.id)"
            ),
            {"cid": catalog_id},
        ).scalar()

        # Pending annotation suggestions
        pending_suggestions = db.execute(
            sa_text(
                "SELECT COUNT(*) FROM annotation_suggestions s"
                " JOIN images i ON i.id = s.image_id"
                " WHERE i.catalog_id = CAST(:cid AS uuid) AND s.status = 'pending'"
            ),
            {"cid": catalog_id},
        ).scalar()

        # Most recent import batch
        last_import = db.execute(
            sa_text(
                "SELECT MAX(organized_path) IS NOT NULL, COUNT(*)"
                " FROM images WHERE catalog_id = CAST(:cid AS uuid)"
                " AND DATE(created_at) = (SELECT MAX(DATE(created_at)) FROM images WHERE catalog_id = CAST(:cid AS uuid))"
            ),
            {"cid": catalog_id},
        ).first()

        # Recent tags (last 10 created)
        recent_tags = db.execute(
            sa_text(
                "SELECT id, label, created_at,"
                " (SELECT COUNT(*) FROM image_tags it WHERE it.tag_id = t.id) as image_count"
                " FROM tags t WHERE catalog_id = CAST(:cid AS uuid)"
                " ORDER BY created_at DESC LIMIT 10"
            ),
            {"cid": catalog_id},
        ).fetchall()

    needs_attention = []
    if pending_groups and pending_groups[0] > 0:
        needs_attention.append({
            "type": "ml_groups",
            "label": f"{pending_groups[0]} unnamed group{'s' if pending_groups[0] != 1 else ''} found",
            "count": pending_groups[0],
            "image_count": int(pending_groups[1]),
            "action": "curate",
        })
    if untagged_count and untagged_count > 0:
        needs_attention.append({
            "type": "untagged",
            "label": f"{untagged_count:,} images have no tags",
            "count": untagged_count,
            "action": "browse_untagged",
        })
    if pending_suggestions and pending_suggestions > 0:
        needs_attention.append({
            "type": "suggestions",
            "label": f"{pending_suggestions} ML suggestions waiting for review",
            "count": pending_suggestions,
            "action": "review_suggestions",
        })

    return {
        "needs_attention": needs_attention,
        "recent_tags": [
            {"id": str(r[0]), "label": r[1],
             "created_at": r[2].isoformat() if r[2] else None,
             "image_count": r[3]}
            for r in recent_tags
        ],
    }
```

**Step 3: Add text search endpoint to catalogs.py**

Find the existing search/images endpoint in `lumina/api/routers/catalogs.py` and add a new endpoint for CLIP text-to-image search:

```python
@router.get("/{catalog_id}/search/")
def search_images(catalog_id: str, q: str, limit: int = 100):
    """CLIP text-to-image similarity search against FAISS index."""
    from lumina.analysis.clip_encoder import encode_text  # implement in Task 6
    from lumina.analysis.scanner import faiss_search

    try:
        text_embedding = encode_text(q)
        image_ids = faiss_search(catalog_id, text_embedding, top_k=limit)
    except Exception:
        image_ids = []

    if not image_ids:
        return {"images": [], "query": q, "method": "clip"}

    with get_db_context() as db:
        placeholders = ", ".join(f"'{iid}'" for iid in image_ids)
        rows = db.execute(
            sa_text(
                f"SELECT id, organized_path, source_path, created_at"
                f" FROM images WHERE id IN ({placeholders})"
                f" AND catalog_id = CAST(:cid AS uuid)"
            ),
            {"cid": catalog_id},
        ).fetchall()

    return {
        "images": [{"id": r[0], "path": r[1] or r[2]} for r in rows],
        "query": q,
        "method": "clip",
    }
```

**Step 4: Run tests**

```bash
python -m pytest tests/api/test_home.py -v
```

**Step 5: Commit**

```bash
git add lumina/api/routers/tags.py lumina/api/routers/catalogs.py tests/api/test_home.py
git commit -m "feat: home screen API and CLIP text search endpoint"
```

---

## Task 6: ML Enrichment Background Job

**Files:**
- Create: `lumina/analysis/clip_encoder.py`
- Create: `lumina/jobs/definitions/ml_enrichment.py`
- Modify: `lumina/jobs/types.py` (add `ml_enrichment` to JobType)
- Modify: `lumina/jobs/definitions/__init__.py` (register job)
- Modify: `lumina/jobs/definitions/camera_import.py` (trigger enrichment after import)

**Step 1: CLIP text encoder**

```python
# lumina/analysis/clip_encoder.py
"""CLIP text encoding for text-to-image search."""

import numpy as np
from pathlib import Path

_model = None
_preprocess = None


def _load():
    global _model, _preprocess
    if _model is None:
        import open_clip
        _model, _, _preprocess = open_clip.create_model_and_transforms(
            "ViT-L-14", pretrained="openai"
        )
        _model.eval()
    return _model


def encode_text(text: str) -> np.ndarray:
    import torch
    import open_clip
    model = _load()
    tokenizer = open_clip.get_tokenizer("ViT-L-14")
    with torch.no_grad():
        tokens = tokenizer([text])
        embedding = model.encode_text(tokens)
        embedding = embedding / embedding.norm(dim=-1, keepdim=True)
    return embedding.squeeze().numpy().astype(np.float32)
```

**Step 2: Implement the enrichment job**

```python
# lumina/jobs/definitions/ml_enrichment.py
"""ML enrichment job — clusters existing images, surfaces ml_groups, generates label hints."""

import logging
import uuid
from typing import Any, Dict

from lumina.db import get_db_context
from ..background_jobs import update_job_status
from ..types import JobContext

logger = logging.getLogger(__name__)

OLLAMA_BASE = "http://ollama:11434"
LABEL_MODEL = "qwen3-vl"


def ml_enrichment_job(ctx: JobContext) -> Dict[str, Any]:
    catalog_id = str(ctx.catalog_id)

    update_job_status(ctx.job_id, "PROGRESS",
                      progress={"message": "Loading FAISS embeddings...", "percent": 0})

    groups_created = 0

    # Phase 1: CLIP visual clustering
    try:
        groups_created += _cluster_visual(catalog_id, ctx.job_id)
    except Exception as e:
        logger.error(f"Visual clustering failed: {e}")

    # Phase 2: Temporal + geo clustering
    try:
        groups_created += _cluster_temporal_geo(catalog_id, ctx.job_id)
    except Exception as e:
        logger.error(f"Temporal/geo clustering failed: {e}")

    # Phase 3: Generate label hints via Ollama
    try:
        _generate_label_hints(catalog_id)
    except Exception as e:
        logger.error(f"Label hint generation failed: {e}")

    return {"groups_created": groups_created, "catalog_id": catalog_id}


def _cluster_visual(catalog_id: str, job_id: str) -> int:
    """HDBSCAN clustering on FAISS embeddings → ml_groups."""
    import numpy as np

    update_job_status(job_id, "PROGRESS",
                      progress={"message": "Clustering images visually...", "percent": 20})

    # Load embeddings from FAISS / database
    with get_db_context() as db:
        rows = db.execute(
            __import__("sqlalchemy").text(
                "SELECT id, embedding FROM images"
                " WHERE catalog_id = CAST(:cid AS uuid)"
                " AND embedding IS NOT NULL"
            ),
            {"cid": catalog_id},
        ).fetchall()

    if len(rows) < 10:
        return 0

    image_ids = [r[0] for r in rows]
    embeddings = np.array([r[1] for r in rows], dtype=np.float32)

    try:
        import hdbscan
        clusterer = hdbscan.HDBSCAN(min_cluster_size=5, min_samples=3, metric="euclidean")
        labels = clusterer.fit_predict(embeddings)
    except ImportError:
        # Fallback: simple k-means if hdbscan not available
        from sklearn.cluster import MiniBatchKMeans
        n_clusters = max(5, len(image_ids) // 200)
        km = MiniBatchKMeans(n_clusters=n_clusters, random_state=42)
        labels = km.fit_predict(embeddings)

    return _save_groups(catalog_id, image_ids, labels, method="clip_cluster")


def _cluster_temporal_geo(catalog_id: str, job_id: str) -> int:
    """DBSCAN on GPS + timestamp → event candidate ml_groups."""
    import numpy as np
    from sqlalchemy import text as sa_text

    update_job_status(job_id, "PROGRESS",
                      progress={"message": "Clustering by time and location...", "percent": 50})

    with get_db_context() as db:
        rows = db.execute(
            sa_text(
                "SELECT id, gps_lat, gps_lon, capture_time FROM images"
                " WHERE catalog_id = CAST(:cid AS uuid)"
                " AND gps_lat IS NOT NULL AND gps_lon IS NOT NULL"
                " AND capture_time IS NOT NULL"
            ),
            {"cid": catalog_id},
        ).fetchall()

    if len(rows) < 5:
        return 0

    image_ids = [r[0] for r in rows]
    # Normalize: lat/lon in degrees, time as days since epoch
    import time
    features = np.array([
        [r[1], r[2], (r[3].timestamp() if r[3] else 0) / 86400]
        for r in rows
    ], dtype=np.float32)

    from sklearn.cluster import DBSCAN
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    features_scaled = scaler.fit_transform(features)
    labels = DBSCAN(eps=0.5, min_samples=3).fit_predict(features_scaled)

    return _save_groups(catalog_id, image_ids, labels, method="temporal_geo")


def _save_groups(catalog_id: str, image_ids: list, labels, method: str) -> int:
    """Persist cluster results as ml_groups, skipping noise (-1) and already-grouped images."""
    from collections import defaultdict
    from sqlalchemy import text as sa_text
    import json

    cluster_map = defaultdict(list)
    for img_id, label in zip(image_ids, labels):
        if label >= 0:
            cluster_map[int(label)].append(img_id)

    created = 0
    with get_db_context() as db:
        for label, members in cluster_map.items():
            if len(members) < 3:
                continue
            group_id = str(uuid.uuid4())
            sample = members[:9]
            db.execute(
                sa_text(
                    "INSERT INTO ml_groups (id, catalog_id, method, image_count, sample_image_ids)"
                    " VALUES (CAST(:id AS uuid), CAST(:cid AS uuid), :method, :count, CAST(:sample AS jsonb))"
                    " ON CONFLICT DO NOTHING"
                ),
                {"id": group_id, "cid": catalog_id, "method": method,
                 "count": len(members), "sample": json.dumps(sample)},
            )
            for img_id in members:
                db.execute(
                    sa_text(
                        "INSERT INTO ml_group_images (group_id, image_id)"
                        " VALUES (CAST(:gid AS uuid), :iid)"
                        " ON CONFLICT DO NOTHING"
                    ),
                    {"gid": group_id, "iid": img_id},
                )
            created += 1
        db.commit()

    return created


def _generate_label_hints(catalog_id: str) -> None:
    """Ask qwen3-vl to draft a label hint for each pending group with no hint."""
    import requests
    import base64
    import json
    from pathlib import Path
    from sqlalchemy import text as sa_text

    with get_db_context() as db:
        groups = db.execute(
            sa_text(
                "SELECT id, sample_image_ids, method FROM ml_groups"
                " WHERE catalog_id = CAST(:cid AS uuid)"
                " AND status = 'pending' AND label_hint IS NULL"
                " LIMIT 20"
            ),
            {"cid": catalog_id},
        ).fetchall()

    for group_id, sample_ids, method in groups:
        try:
            hint = _draft_hint(sample_ids[:3], method)
            if hint:
                with get_db_context() as db:
                    db.execute(
                        sa_text("UPDATE ml_groups SET label_hint = :hint WHERE id = CAST(:id AS uuid)"),
                        {"hint": hint, "id": str(group_id)},
                    )
                    db.commit()
        except Exception as e:
            logger.warning(f"Label hint failed for group {group_id}: {e}")


def _draft_hint(sample_image_ids: list, method: str) -> str:
    """Ask qwen3-vl to describe a group of images and suggest a short name."""
    import requests
    import base64
    from pathlib import Path
    from sqlalchemy import text as sa_text

    images_b64 = []
    with get_db_context() as db:
        for img_id in sample_image_ids:
            row = db.execute(
                sa_text("SELECT organized_path, source_path FROM images WHERE id = :id"),
                {"id": img_id},
            ).first()
            if not row:
                continue
            path = Path(row[0] or row[1] or "")
            if path.exists():
                try:
                    with open(path, "rb") as f:
                        images_b64.append(base64.b64encode(f.read()).decode())
                except Exception:
                    pass

    if not images_b64:
        return ""

    prompt = (
        "These images are from a photo library. They were grouped by visual similarity"
        f" using {method}. "
        "In 2-4 words, suggest a short descriptive label for this group. "
        "Examples: 'family scans', 'yellowstone trip', 'office whiteboards', 'portraits outdoors'. "
        "Reply with only the label, nothing else."
    )

    payload = {
        "model": LABEL_MODEL,
        "prompt": prompt,
        "images": images_b64,
        "stream": False,
    }
    resp = requests.post(f"{OLLAMA_BASE}/api/generate", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json().get("response", "").strip()[:80]
```

**Step 3: Register job type and handler**

In `lumina/jobs/types.py`, add `ml_enrichment = "ml_enrichment"` to the `JobType` enum.

In `lumina/jobs/definitions/__init__.py`, import and register:
```python
from .ml_enrichment import ml_enrichment_job
# add to JOB_REGISTRY:
JobType.ml_enrichment: ml_enrichment_job,
```

**Step 4: Trigger after camera import**

At the end of `camera_import_job()` in `lumina/jobs/definitions/camera_import.py`, after the `_upsert_last_import_collection` call, add:

```python
    # Trigger ML enrichment for new images
    from lumina.jobs.background_jobs import enqueue_job
    from lumina.jobs.types import JobType
    enqueue_job(JobType.ml_enrichment, catalog_id=str(ctx.catalog_id), priority=30)
```

**Step 5: Test**

```bash
# Manually trigger enrichment job via API
CATALOG_ID=$(docker compose exec db psql -U lumina -d lumina -t -c "SELECT id FROM catalogs LIMIT 1" | tr -d ' ')
curl -s -X POST "http://localhost:8000/catalogs/$CATALOG_ID/jobs/" \
  -H "Content-Type: application/json" \
  -d '{"job_type": "ml_enrichment"}' | python3 -m json.tool

# After job completes, check for groups
curl -s "http://localhost:8000/catalogs/$CATALOG_ID/ml-groups/" | python3 -m json.tool | head -40
```

**Step 6: Commit**

```bash
git add lumina/analysis/clip_encoder.py lumina/jobs/definitions/ml_enrichment.py \
        lumina/jobs/types.py lumina/jobs/definitions/__init__.py \
        lumina/jobs/definitions/camera_import.py
git commit -m "feat: ML enrichment job — CLIP clustering, temporal/geo clustering, qwen3-vl label hints"
```

---

## Task 7: Frontend — Stores

**Files:**
- Create: `src/stores/tags.ts`
- Create: `src/stores/home.ts`
- Create: `src/stores/curate.ts`

**Step 1: Tags store**

```typescript
// src/stores/tags.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useCatalogStore } from './catalog'

export interface Tag {
  id: string
  slug: string
  label: string
  parent_id: string | null
  notes: string | null
  image_count: number
  created_at: string
}

export const useTagsStore = defineStore('tags', () => {
  const catalogStore = useCatalogStore()
  const tags = ref<Tag[]>([])
  const loading = ref(false)

  const tagTree = computed(() => {
    const roots = tags.value.filter(t => !t.parent_id)
    const children = (parentId: string) => tags.value.filter(t => t.parent_id === parentId)
    const buildTree = (tag: Tag): Tag & { children: any[] } => ({
      ...tag,
      children: children(tag.id).map(buildTree),
    })
    return roots.map(buildTree)
  })

  const tagById = computed(() => {
    const map: Record<string, Tag> = {}
    tags.value.forEach(t => { map[t.id] = t })
    return map
  })

  async function fetchTags() {
    const id = catalogStore.activeCatalog?.id
    if (!id) return
    loading.value = true
    try {
      const resp = await fetch(`/api/catalogs/${id}/tags/`)
      tags.value = await resp.json()
    } finally {
      loading.value = false
    }
  }

  async function createTag(label: string, parent_id?: string): Promise<Tag> {
    const id = catalogStore.activeCatalog!.id
    const resp = await fetch(`/api/catalogs/${id}/tags/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label, parent_id }),
    })
    const tag = await resp.json()
    tags.value.push(tag)
    return tag
  }

  async function deleteTag(tagId: string) {
    const id = catalogStore.activeCatalog!.id
    await fetch(`/api/catalogs/${id}/tags/${tagId}/`, { method: 'DELETE' })
    tags.value = tags.value.filter(t => t.id !== tagId)
  }

  async function bulkTag(imageIds: string[], tagId: string) {
    const id = catalogStore.activeCatalog!.id
    const resp = await fetch(`/api/catalogs/${id}/images/tag/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_ids: imageIds, tag_id: tagId }),
    })
    return resp.json()
  }

  async function bulkUntag(imageIds: string[], tagId: string) {
    const id = catalogStore.activeCatalog!.id
    const resp = await fetch(`/api/catalogs/${id}/images/tag/`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_ids: imageIds, tag_id: tagId }),
    })
    return resp.json()
  }

  return { tags, loading, tagTree, tagById, fetchTags, createTag, deleteTag, bulkTag, bulkUntag }
})
```

```typescript
// src/stores/home.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useCatalogStore } from './catalog'

export interface AttentionItem {
  type: string
  label: string
  count: number
  image_count?: number
  action: string
}

export const useHomeStore = defineStore('home', () => {
  const catalogStore = useCatalogStore()
  const needsAttention = ref<AttentionItem[]>([])
  const recentTags = ref<any[]>([])
  const loading = ref(false)

  async function fetchHome() {
    const id = catalogStore.activeCatalog?.id
    if (!id) return
    loading.value = true
    try {
      const resp = await fetch(`/api/catalogs/${id}/home/`)
      const data = await resp.json()
      needsAttention.value = data.needs_attention
      recentTags.value = data.recent_tags
    } finally {
      loading.value = false
    }
  }

  return { needsAttention, recentTags, loading, fetchHome }
})
```

```typescript
// src/stores/curate.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useCatalogStore } from './catalog'

export interface MlGroup {
  id: string
  method: string
  label_hint: string | null
  image_count: number
  sample_image_ids: string[]
  signals: Record<string, any>
  status: string
}

export const useCurateStore = defineStore('curate', () => {
  const catalogStore = useCatalogStore()
  const groups = ref<MlGroup[]>([])
  const loading = ref(false)

  async function fetchGroups() {
    const id = catalogStore.activeCatalog?.id
    if (!id) return
    loading.value = true
    try {
      const resp = await fetch(`/api/catalogs/${id}/ml-groups/`)
      groups.value = await resp.json()
    } finally {
      loading.value = false
    }
  }

  async function nameGroup(groupId: string, label: string, parentId?: string) {
    const id = catalogStore.activeCatalog!.id
    const resp = await fetch(`/api/catalogs/${id}/ml-groups/${groupId}/name/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label, parent_id: parentId }),
    })
    const result = await resp.json()
    groups.value = groups.value.filter(g => g.id !== groupId)
    return result
  }

  async function skipGroup(groupId: string) {
    const id = catalogStore.activeCatalog!.id
    await fetch(`/api/catalogs/${id}/ml-groups/${groupId}/skip/`, { method: 'POST' })
    groups.value = groups.value.filter(g => g.id !== groupId)
  }

  async function deleteGroup(groupId: string) {
    const id = catalogStore.activeCatalog!.id
    await fetch(`/api/catalogs/${id}/ml-groups/${groupId}/delete/`, { method: 'POST' })
    groups.value = groups.value.filter(g => g.id !== groupId)
  }

  return { groups, loading, fetchGroups, nameGroup, skipGroup, deleteGroup }
})
```

**Step 2: Commit**

```bash
git add src/stores/tags.ts src/stores/home.ts src/stores/curate.ts
# (frontend build happens in Task 11)
```

---

## Task 8: Frontend — Home Screen View

**Files:**
- Create: `src/views/HomeView.vue`
- Modify: `src/router/index.ts` (make HomeView the default route)

**Step 1: Implement HomeView**

```vue
<!-- src/views/HomeView.vue -->
<template>
  <div class="flex flex-col h-full p-8 max-w-3xl mx-auto">
    <h1 class="text-2xl font-semibold text-white mb-2">Your Library</h1>
    <p class="text-gray-400 text-sm mb-8">{{ totalImages.toLocaleString() }} images</p>

    <!-- Search -->
    <div class="mb-8">
      <div class="relative">
        <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
        <input
          v-model="searchQuery"
          @keydown.enter="runSearch"
          placeholder="What are you looking for?"
          class="w-full bg-gray-800 text-white pl-10 pr-4 py-3 rounded-lg border border-gray-700 focus:border-blue-500 focus:outline-none text-sm"
        />
      </div>
    </div>

    <!-- Loading -->
    <div v-if="homeStore.loading" class="text-gray-500 text-sm">Loading...</div>

    <!-- Needs Attention -->
    <section v-if="homeStore.needsAttention.length > 0" class="mb-8">
      <h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Needs Attention</h2>
      <div class="space-y-2">
        <button
          v-for="item in homeStore.needsAttention"
          :key="item.type"
          @click="handleAction(item)"
          class="w-full text-left px-4 py-3 bg-gray-800 hover:bg-gray-750 rounded-lg border border-gray-700 hover:border-gray-600 transition-colors"
        >
          <div class="flex items-center justify-between">
            <span class="text-sm text-white">{{ item.label }}</span>
            <ChevronRight class="w-4 h-4 text-gray-500" />
          </div>
          <p v-if="item.image_count" class="text-xs text-gray-500 mt-0.5">
            {{ item.image_count.toLocaleString() }} images
          </p>
        </button>
      </div>
    </section>

    <!-- Recent Tags -->
    <section v-if="homeStore.recentTags.length > 0">
      <h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Recent</h2>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="tag in homeStore.recentTags"
          :key="tag.id"
          @click="openTag(tag)"
          class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded-full text-sm text-gray-300 border border-gray-700 transition-colors"
        >
          {{ tag.label }}
          <span class="text-gray-500 ml-1">{{ tag.image_count }}</span>
        </button>
      </div>
    </section>

    <!-- Empty state -->
    <div v-if="!homeStore.loading && homeStore.needsAttention.length === 0 && homeStore.recentTags.length === 0"
         class="text-center text-gray-600 mt-16">
      <p class="text-sm">Import some photos to get started.</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Search, ChevronRight } from 'lucide-vue-next'
import { useHomeStore } from '@/stores/home'
import { useCatalogStore } from '@/stores/catalog'

const router = useRouter()
const homeStore = useHomeStore()
const catalogStore = useCatalogStore()
const searchQuery = ref('')

const totalImages = computed(() => catalogStore.activeCatalog?.image_count ?? 0)

onMounted(() => homeStore.fetchHome())

function runSearch() {
  if (!searchQuery.value.trim()) return
  router.push({ name: 'library', query: { q: searchQuery.value } })
}

function handleAction(item: any) {
  if (item.action === 'curate') router.push({ name: 'curate' })
  else if (item.action === 'browse_untagged') router.push({ name: 'library', query: { filter: 'untagged' } })
  else if (item.action === 'review_suggestions') router.push({ name: 'curate', query: { mode: 'suggestions' } })
}

function openTag(tag: any) {
  router.push({ name: 'library', query: { tag: tag.id } })
}
</script>
```

**Step 2: Update router**

In `src/router/index.ts`, change the default route from LibraryView to HomeView:

```typescript
import HomeView from '@/views/HomeView.vue'

// Change the '/' route:
{ path: '/', name: 'home', component: HomeView },
// Keep library as a named route:
{ path: '/library', name: 'library', component: LibraryView },
// Add curate route:
{ path: '/curate', name: 'curate', component: CurateView },
```

**Step 3: Commit source**

```bash
git add src/views/HomeView.vue src/router/index.ts
```

---

## Task 9: Frontend — Tag Tree + Navigation

**Files:**
- Create: `src/components/library/TagTree.vue`
- Modify: `src/components/library/NavigationSidebar.vue`
- Modify: `src/layouts/LibraryLayout.vue` (update top nav)

**Step 1: TagTree component**

```vue
<!-- src/components/library/TagTree.vue -->
<template>
  <div class="flex flex-col h-full">
    <div class="px-3 py-2">
      <input
        v-model="search"
        placeholder="Filter tags..."
        class="w-full bg-gray-900 text-gray-300 text-xs px-2 py-1.5 rounded border border-gray-700 focus:outline-none focus:border-gray-600"
      />
    </div>
    <div class="flex-1 overflow-y-auto px-2 py-1">
      <div v-if="tagsStore.loading" class="text-gray-600 text-xs px-2 py-2">Loading...</div>
      <TagTreeNode
        v-for="tag in filteredTree"
        :key="tag.id"
        :tag="tag"
        :active-tag-id="activeTagId"
        @select="$emit('select', $event)"
      />
      <div v-if="!tagsStore.loading && tagsStore.tags.length === 0"
           class="text-gray-600 text-xs px-2 py-4 text-center">
        No tags yet.<br/>Start curating to create them.
      </div>
    </div>
    <div class="px-3 py-2 border-t border-gray-800">
      <button
        @click="$emit('import')"
        class="w-full flex items-center gap-2 px-2 py-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors"
      >
        <Download class="w-3.5 h-3.5" />
        Import
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Download } from 'lucide-vue-next'
import { useTagsStore } from '@/stores/tags'
import TagTreeNode from './TagTreeNode.vue'

const props = defineProps<{ activeTagId?: string }>()
defineEmits(['select', 'import'])

const tagsStore = useTagsStore()
const search = ref('')

const filteredTree = computed(() => {
  if (!search.value) return tagsStore.tagTree
  const q = search.value.toLowerCase()
  return tagsStore.tags
    .filter(t => t.label.toLowerCase().includes(q))
    .map(t => ({ ...t, children: [] }))
})

onMounted(() => tagsStore.fetchTags())
</script>
```

```vue
<!-- src/components/library/TagTreeNode.vue -->
<template>
  <div>
    <button
      @click="$emit('select', tag)"
      :class="[
        'w-full flex items-center gap-2 px-2 py-1.5 rounded text-sm text-left transition-colors',
        activeTagId === tag.id
          ? 'bg-blue-600 text-white'
          : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
      ]"
    >
      <component :is="tag.children?.length ? FolderOpen : Tag" class="w-3.5 h-3.5 shrink-0" />
      <span class="flex-1 truncate">{{ tag.label }}</span>
      <span class="text-xs opacity-50">{{ tag.image_count }}</span>
    </button>
    <div v-if="tag.children?.length" class="ml-4">
      <TagTreeNode
        v-for="child in tag.children"
        :key="child.id"
        :tag="child"
        :active-tag-id="activeTagId"
        @select="$emit('select', $event)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { Tag, FolderOpen } from 'lucide-vue-next'
defineProps<{ tag: any; activeTagId?: string }>()
defineEmits(['select'])
</script>
```

**Step 2: Update NavigationSidebar**

Replace the existing collection list with `<TagTree>`. Keep the top navigation (Library | Curate) and remove the old system collection entries.

**Step 3: Update LibraryLayout top nav**

Change from `Library | Import | Triage` to `Library | Curate`, with the Import button in the tag tree footer.

**Step 4: Commit source**

```bash
git add src/components/library/TagTree.vue src/components/library/TagTreeNode.vue \
        src/components/library/NavigationSidebar.vue src/layouts/LibraryLayout.vue
```

---

## Task 10: Frontend — Curate Mode

**Files:**
- Create: `src/views/CurateView.vue`
- Create: `src/components/curate/GroupQueue.vue`
- Create: `src/components/curate/GroupGrid.vue`
- Create: `src/components/curate/GroupActions.vue`

**Step 1: CurateView**

```vue
<!-- src/views/CurateView.vue -->
<template>
  <div class="flex h-full">
    <!-- Left: group queue -->
    <div class="w-64 border-r border-gray-800 flex flex-col">
      <div class="px-4 py-3 border-b border-gray-800">
        <h2 class="text-sm font-medium text-white">Unnamed Groups</h2>
        <p class="text-xs text-gray-500">{{ curateStore.groups.length }} pending</p>
      </div>
      <GroupQueue
        :groups="curateStore.groups"
        :active-id="activeGroupId"
        @select="selectGroup"
      />
    </div>

    <!-- Center: group images -->
    <div class="flex-1 flex flex-col">
      <div v-if="!activeGroup" class="flex-1 flex items-center justify-center text-gray-600 text-sm">
        Select a group to review
      </div>
      <GroupGrid
        v-else
        :group="activeGroup"
        :selected-ids="selectedImageIds"
        @toggle="toggleImage"
        @select-all="selectAll"
        @deselect-all="deselectAll"
      />
    </div>

    <!-- Right: naming controls -->
    <div class="w-72 border-l border-gray-800">
      <GroupActions
        v-if="activeGroup"
        :group="activeGroup"
        :selected-count="selectedImageIds.length"
        @name="handleName"
        @skip="handleSkip"
        @delete="handleDelete"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useCurateStore } from '@/stores/curate'
import GroupQueue from '@/components/curate/GroupQueue.vue'
import GroupGrid from '@/components/curate/GroupGrid.vue'
import GroupActions from '@/components/curate/GroupActions.vue'

const curateStore = useCurateStore()
const activeGroupId = ref<string | null>(null)
const selectedImageIds = ref<string[]>([])

const activeGroup = computed(() =>
  curateStore.groups.find(g => g.id === activeGroupId.value) ?? null
)

onMounted(() => curateStore.fetchGroups())

function selectGroup(group: any) {
  activeGroupId.value = group.id
  selectedImageIds.value = []
}

function toggleImage(id: string) {
  const idx = selectedImageIds.value.indexOf(id)
  if (idx >= 0) selectedImageIds.value.splice(idx, 1)
  else selectedImageIds.value.push(id)
}

function selectAll() {
  // populated from GroupGrid via emit or store
}

function deselectAll() {
  selectedImageIds.value = []
}

async function handleName(label: string) {
  if (!activeGroupId.value) return
  await curateStore.nameGroup(activeGroupId.value, label)
  activeGroupId.value = curateStore.groups[0]?.id ?? null
  selectedImageIds.value = []
}

async function handleSkip() {
  if (!activeGroupId.value) return
  await curateStore.skipGroup(activeGroupId.value)
  activeGroupId.value = curateStore.groups[0]?.id ?? null
}

async function handleDelete() {
  if (!activeGroupId.value) return
  await curateStore.deleteGroup(activeGroupId.value)
  activeGroupId.value = curateStore.groups[0]?.id ?? null
}
</script>
```

The `GroupQueue`, `GroupGrid`, and `GroupActions` sub-components are straightforward list/grid/form components — implement with TailwindCSS following the existing component patterns in `src/components/library/`.

`GroupGrid` should load image thumbnails using the existing thumbnail endpoint (`/api/catalogs/{id}/images/{image_id}/thumbnail`) and render them in a responsive grid with checkbox overlay for bulk selection. Keyboard: `A` = select all, `D` = deselect all, `→`/`←` = navigate groups.

`GroupActions` should have: a text input for the label (pre-filled with `label_hint` if present), a tag parent selector (optional), and three buttons: Name, Skip, Delete.

**Step 2: Commit source**

```bash
git add src/views/CurateView.vue src/components/curate/
```

---

## Task 11: Build, Cleanup, Final Commit

**Files:**
- Delete: `src/views/TriageView.vue` (replaced by CurateView)
- Modify: remove TriageView from router
- Build frontend
- Commit static assets

**Step 1: Remove TriageView**

```bash
rm src/views/TriageView.vue
# Remove from src/router/index.ts
```

**Step 2: Build**

```bash
cd /home/irjudson/Projects/lumina
npm run build
```

Expected: build succeeds, output in `lumina/web/static/`.

**Step 3: Verify in browser**

```bash
# Check the app loads, home screen shows needs_attention items
# Navigate to Curate — groups queue visible
# Click a tag in left panel — scoped grid loads
```

**Step 4: Final commit**

```bash
git add lumina/web/static/ src/
git commit -m "feat: curation system UI — home screen, tag tree, curate mode, remove triage view"
```

---

## Execution Order

Tasks 1–3 are pure backend and can be verified immediately with curl. Recommended to build
and test these before proceeding to Tasks 4–6. Tasks 7–11 are frontend and require a build
to verify. Run as a batch once backend is confirmed working.

**First batch (backend only):** Tasks 1, 2, 3, 4, 5
**Second batch (ML pipeline):** Task 6
**Third batch (frontend):** Tasks 7, 8, 9, 10, 11
