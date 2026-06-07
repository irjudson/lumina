"""Migrate face person-collections and travel collection to folk_tags. Delete empty system collections."""

import logging
import re

from sqlalchemy import text

logger = logging.getLogger(__name__)

EMPTY_SYSTEM_KEYS = {
    "family_personal",
    "work_professional",
    "archival",
    "projects",
    "last_import",
}

_DONE_MARKER = "collections_to_tags_v1"


def upgrade(engine) -> None:
    # Idempotency: skip if already run (marker stored in routing_rules)
    with engine.connect() as conn:
        try:
            exists = conn.execute(
                text("SELECT 1 FROM routing_rules WHERE task = :marker LIMIT 1"),
                {"marker": _DONE_MARKER},
            ).first()
            if exists:
                logger.info("collections_to_tags already applied, skipping")
                return
        except Exception:
            pass  # routing_rules may not exist yet; fall through

    with engine.connect() as conn:
        catalogs = conn.execute(text("SELECT id FROM catalogs")).fetchall()
        for (catalog_id,) in catalogs:
            _migrate_travel(conn, str(catalog_id))
            _migrate_people(conn, str(catalog_id))
        _delete_empty_collections(conn)
        conn.commit()

    # Record completion marker
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    "INSERT INTO routing_rules (task, model, source)"
                    " VALUES (:marker, 'migration', 'migration')"
                    " ON CONFLICT DO NOTHING"
                ),
                {"marker": _DONE_MARKER},
            )
            conn.commit()
        except Exception as e:
            logger.warning(f"Could not write migration marker: {e}")

    logger.info("collections_to_tags migration applied")


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower())[:80].strip("_") or "tag"


def _migrate_travel(conn, catalog_id: str) -> None:
    """Travel collection + sub-collections -> folk_tags hierarchy."""
    travel = conn.execute(
        text(
            "SELECT id FROM collections"
            " WHERE catalog_id = CAST(:cid AS uuid) AND system_key = 'travel' LIMIT 1"
        ),
        {"cid": catalog_id},
    ).first()
    if not travel:
        return

    travel_tag_id = conn.execute(
        text(
            "INSERT INTO folk_tags (catalog_id, slug, label)"
            " VALUES (CAST(:cid AS uuid), 'travel', 'Travel')"
            " ON CONFLICT (catalog_id, slug) DO UPDATE SET label = EXCLUDED.label"
            " RETURNING id"
        ),
        {"cid": catalog_id},
    ).scalar()

    children = conn.execute(
        text(
            "SELECT id, name FROM collections"
            " WHERE catalog_id = CAST(:cid AS uuid) AND parent_id = CAST(:pid AS uuid)"
        ),
        {"cid": catalog_id, "pid": str(travel[0])},
    ).fetchall()

    for child_id, child_name in children:
        slug = _slugify(child_name)
        child_tag_id = conn.execute(
            text(
                "INSERT INTO folk_tags (catalog_id, slug, label, parent_id)"
                " VALUES (CAST(:cid AS uuid), :slug, :label, CAST(:parent AS uuid))"
                " ON CONFLICT (catalog_id, slug) DO UPDATE SET label = EXCLUDED.label"
                " RETURNING id"
            ),
            {
                "cid": catalog_id,
                "slug": slug,
                "label": child_name,
                "parent": str(travel_tag_id),
            },
        ).scalar()

        images = conn.execute(
            text(
                "SELECT image_id FROM collection_images"
                " WHERE collection_id = CAST(:cid AS uuid)"
            ),
            {"cid": str(child_id)},
        ).fetchall()
        for (image_id,) in images:
            conn.execute(
                text(
                    "INSERT INTO folk_image_tags (image_id, tag_id, source)"
                    " VALUES (:iid, CAST(:tid AS uuid), 'migration')"
                    " ON CONFLICT DO NOTHING"
                ),
                {"iid": image_id, "tid": str(child_tag_id)},
            )

    logger.info(
        f"Migrated travel collection for catalog {catalog_id}: {len(children)} sub-tags"
    )


def _migrate_people(conn, catalog_id: str) -> None:
    """Face person-collections -> folk_tags + people records + image_people links."""
    people_coll = conn.execute(
        text(
            "SELECT id FROM collections"
            " WHERE catalog_id = CAST(:cid AS uuid) AND system_key = 'people' LIMIT 1"
        ),
        {"cid": catalog_id},
    ).first()
    if not people_coll:
        return

    persons = conn.execute(
        text(
            "SELECT id, name FROM collections"
            " WHERE catalog_id = CAST(:cid AS uuid) AND parent_id = CAST(:pid AS uuid)"
        ),
        {"cid": catalog_id, "pid": str(people_coll[0])},
    ).fetchall()

    for person_coll_id, person_name in persons:
        slug = "person_" + _slugify(person_name)[:60]
        tag_id = conn.execute(
            text(
                "INSERT INTO folk_tags (catalog_id, slug, label)"
                " VALUES (CAST(:cid AS uuid), :slug, :label)"
                " ON CONFLICT (catalog_id, slug) DO UPDATE SET label = EXCLUDED.label"
                " RETURNING id"
            ),
            {"cid": catalog_id, "slug": slug, "label": person_name},
        ).scalar()

        person_id = conn.execute(
            text(
                "INSERT INTO people (catalog_id, tag_id, name)"
                " VALUES (CAST(:cid AS uuid), CAST(:tid AS uuid), :name)"
                " ON CONFLICT DO NOTHING RETURNING id"
            ),
            {"cid": catalog_id, "tid": str(tag_id), "name": person_name},
        ).scalar()
        if not person_id:
            person_id = conn.execute(
                text(
                    "SELECT id FROM people"
                    " WHERE catalog_id = CAST(:cid AS uuid) AND name = :name LIMIT 1"
                ),
                {"cid": catalog_id, "name": person_name},
            ).scalar()

        images = conn.execute(
            text(
                "SELECT image_id FROM collection_images"
                " WHERE collection_id = CAST(:cid AS uuid)"
            ),
            {"cid": str(person_coll_id)},
        ).fetchall()
        for (image_id,) in images:
            conn.execute(
                text(
                    "INSERT INTO folk_image_tags (image_id, tag_id, source)"
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
    """Delete the pre-defined system collections that were never meaningfully used."""
    deleted = conn.execute(
        text(
            "DELETE FROM collections WHERE system_key = ANY(:keys) RETURNING system_key"
        ),
        {"keys": list(EMPTY_SYSTEM_KEYS)},
    ).fetchall()
    if deleted:
        logger.info(f"Deleted empty system collections: {[r[0] for r in deleted]}")
