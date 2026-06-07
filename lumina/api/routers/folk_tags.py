"""Folksonomy tag API — folk_tags, folk_image_tags, ml_groups, home screen."""

import re
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from lumina.db import get_db_context

router = APIRouter()


def _slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower().strip())
    return slug[:80].strip("_") or "tag"


def _unique_slug(conn, catalog_id: str, base_slug: str) -> str:
    slug = base_slug
    suffix = 1
    while conn.execute(
        sa_text(
            "SELECT 1 FROM folk_tags WHERE catalog_id = CAST(:cid AS uuid) AND slug = :slug"
        ),
        {"cid": catalog_id, "slug": slug},
    ).first():
        slug = f"{base_slug}_{suffix}"
        suffix += 1
    return slug


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


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


class NameGroupRequest(BaseModel):
    label: str
    parent_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Folk-tag CRUD
# ---------------------------------------------------------------------------


@router.get("/{catalog_id}/folk-tags")
def list_folk_tags(catalog_id: str):
    """Return all folk_tags for a catalog as a flat list (client builds tree)."""
    with get_db_context() as db:
        rows = db.execute(
            sa_text(
                "SELECT t.id, t.slug, t.label, t.parent_id, t.notes, t.created_at,"
                " COUNT(fi.image_id) AS image_count"
                " FROM folk_tags t"
                " LEFT JOIN folk_image_tags fi ON fi.tag_id = t.id"
                " WHERE t.catalog_id = CAST(:cid AS uuid)"
                " GROUP BY t.id"
                " ORDER BY t.label"
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


@router.post("/{catalog_id}/folk-tags", status_code=201)
def create_folk_tag(catalog_id: str, body: TagCreate):
    tag_id = str(uuid.uuid4())
    with get_db_context() as db:
        slug = _unique_slug(db, catalog_id, _slugify(body.label))
        db.execute(
            sa_text(
                "INSERT INTO folk_tags (id, catalog_id, slug, label, parent_id, notes)"
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
    return {
        "id": tag_id,
        "slug": slug,
        "label": body.label,
        "parent_id": body.parent_id,
        "notes": body.notes,
        "image_count": 0,
    }


@router.patch("/{catalog_id}/folk-tags/{tag_id}")
def update_folk_tag(catalog_id: str, tag_id: str, body: TagUpdate):
    with get_db_context() as db:
        existing = db.execute(
            sa_text(
                "SELECT id FROM folk_tags"
                " WHERE id = CAST(:id AS uuid) AND catalog_id = CAST(:cid AS uuid)"
            ),
            {"id": tag_id, "cid": catalog_id},
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Tag not found")

        updates: dict = {}
        if body.label is not None:
            updates["label"] = body.label
        if body.parent_id is not None:
            updates["parent_id"] = body.parent_id
        if body.notes is not None:
            updates["notes"] = body.notes

        if updates:
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            db.execute(
                sa_text(
                    f"UPDATE folk_tags SET {set_clause}" " WHERE id = CAST(:id AS uuid)"
                ),
                {**updates, "id": tag_id},
            )
            db.commit()
    return {"id": tag_id, **updates}


@router.delete("/{catalog_id}/folk-tags/{tag_id}", status_code=204)
def delete_folk_tag(catalog_id: str, tag_id: str):
    with get_db_context() as db:
        db.execute(
            sa_text(
                "DELETE FROM folk_tags"
                " WHERE id = CAST(:id AS uuid) AND catalog_id = CAST(:cid AS uuid)"
            ),
            {"id": tag_id, "cid": catalog_id},
        )
        db.commit()


# ---------------------------------------------------------------------------
# Bulk tag / untag images
# ---------------------------------------------------------------------------


@router.post("/{catalog_id}/images/folk-tag")
def bulk_folk_tag(catalog_id: str, body: BulkTagRequest):
    """Add a folk tag to multiple images."""
    with get_db_context() as db:
        if not db.execute(
            sa_text(
                "SELECT 1 FROM folk_tags"
                " WHERE id = CAST(:id AS uuid) AND catalog_id = CAST(:cid AS uuid)"
            ),
            {"id": body.tag_id, "cid": catalog_id},
        ).first():
            raise HTTPException(status_code=404, detail="Tag not found")

        now = datetime.utcnow().isoformat()
        tagged = 0
        for image_id in body.image_ids:
            db.execute(
                sa_text(
                    "INSERT INTO folk_image_tags (image_id, tag_id, source, annotated_at)"
                    " VALUES (:iid, CAST(:tid AS uuid), 'human', :now)"
                    " ON CONFLICT DO NOTHING"
                ),
                {"iid": image_id, "tid": body.tag_id, "now": now},
            )
            tagged += 1
        db.commit()
    return {"tagged": tagged}


@router.delete("/{catalog_id}/images/folk-tag")
def bulk_folk_untag(catalog_id: str, body: BulkTagRequest):
    """Remove a folk tag from multiple images."""
    with get_db_context() as db:
        untagged = 0
        for image_id in body.image_ids:
            result = db.execute(
                sa_text(
                    "DELETE FROM folk_image_tags"
                    " WHERE image_id = :iid AND tag_id = CAST(:tid AS uuid)"
                ),
                {"iid": image_id, "tid": body.tag_id},
            )
            untagged += result.rowcount
        db.commit()
    return {"untagged": untagged}


# ---------------------------------------------------------------------------
# ML Groups
# ---------------------------------------------------------------------------


@router.get("/{catalog_id}/ml-groups")
def list_ml_groups(catalog_id: str, status: str = "pending"):
    with get_db_context() as db:
        rows = db.execute(
            sa_text(
                "SELECT id, method, label_hint, image_count,"
                " sample_image_ids, signals, status, created_at"
                " FROM ml_groups"
                " WHERE catalog_id = CAST(:cid AS uuid) AND status = :status"
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


@router.get("/{catalog_id}/ml-groups/{group_id}/images")
def list_group_images(catalog_id: str, group_id: str, limit: int = 200):
    """Return images belonging to an ML group, with enough metadata to render thumbnails."""
    with get_db_context() as db:
        rows = db.execute(
            sa_text(
                "SELECT i.id, i.thumbnail_path, i.capture_time, i.source_path,"
                "  mgi.score"
                " FROM ml_group_images mgi"
                " JOIN images i ON i.id = mgi.image_id"
                " JOIN ml_groups mg ON mg.id = mgi.group_id"
                " WHERE mgi.group_id = CAST(:gid AS uuid)"
                "   AND mg.catalog_id = CAST(:cid AS uuid)"
                " ORDER BY mgi.score DESC NULLS LAST, i.capture_time"
                " LIMIT :lim"
            ),
            {"gid": group_id, "cid": catalog_id, "lim": limit},
        ).fetchall()
    return [
        {
            "id": str(r[0]),
            "thumbnail_path": r[1],
            "capture_time": r[2].isoformat() if r[2] else None,
            "source_path": r[3],
            "score": r[4],
        }
        for r in rows
    ]


@router.post("/{catalog_id}/ml-groups/{group_id}/name")
def name_ml_group(catalog_id: str, group_id: str, body: NameGroupRequest):
    """Name an ML group — creates or reuses a folk tag and annotates all member images.

    If a tag with the same label already exists in this catalog, the group's images
    are merged into that existing tag rather than creating a duplicate.
    """
    now = datetime.utcnow().isoformat()

    with get_db_context() as db:
        if not db.execute(
            sa_text(
                "SELECT 1 FROM ml_groups"
                " WHERE id = CAST(:id AS uuid) AND catalog_id = CAST(:cid AS uuid)"
            ),
            {"id": group_id, "cid": catalog_id},
        ).first():
            raise HTTPException(status_code=404, detail="Group not found")

        # Reuse existing tag if the label already exists, merging images into it.
        existing = db.execute(
            sa_text(
                "SELECT id, slug FROM folk_tags"
                " WHERE catalog_id = CAST(:cid AS uuid) AND label = :label"
                " LIMIT 1"
            ),
            {"cid": catalog_id, "label": body.label},
        ).first()

        if existing:
            tag_id = str(existing.id)
            slug = existing.slug
        else:
            tag_id = str(uuid.uuid4())
            slug = _unique_slug(db, catalog_id, _slugify(body.label))
            db.execute(
                sa_text(
                    "INSERT INTO folk_tags (id, catalog_id, slug, label, parent_id)"
                    " VALUES (CAST(:id AS uuid), CAST(:cid AS uuid), :slug, :label,"
                    " CAST(:parent AS uuid))"
                ),
                {
                    "id": tag_id,
                    "cid": catalog_id,
                    "slug": slug,
                    "label": body.label,
                    "parent": body.parent_id,
                },
            )

        images = db.execute(
            sa_text(
                "SELECT image_id FROM ml_group_images"
                " WHERE group_id = CAST(:gid AS uuid)"
            ),
            {"gid": group_id},
        ).fetchall()

        for (image_id,) in images:
            db.execute(
                sa_text(
                    "INSERT INTO folk_image_tags (image_id, tag_id, source, annotated_at)"
                    " VALUES (:iid, CAST(:tid AS uuid), 'ml_confirmed', :now)"
                    " ON CONFLICT DO NOTHING"
                ),
                {"iid": image_id, "tid": tag_id, "now": now},
            )

        db.execute(
            sa_text(
                "UPDATE ml_groups"
                " SET status = 'named', tag_id = CAST(:tid AS uuid), reviewed_at = :now"
                " WHERE id = CAST(:gid AS uuid)"
            ),
            {"tid": tag_id, "now": now, "gid": group_id},
        )
        db.commit()

    return {
        "tag": {
            "id": tag_id,
            "slug": slug,
            "label": body.label,
            "image_count": len(images),
        },
        "group": {"id": group_id, "status": "named"},
    }


@router.post("/{catalog_id}/ml-groups/{group_id}/skip")
def skip_ml_group(catalog_id: str, group_id: str):
    now = datetime.utcnow().isoformat()
    with get_db_context() as db:
        db.execute(
            sa_text(
                "UPDATE ml_groups SET status = 'skipped', reviewed_at = :now"
                " WHERE id = CAST(:id AS uuid) AND catalog_id = CAST(:cid AS uuid)"
            ),
            {"now": now, "id": group_id, "cid": catalog_id},
        )
        db.commit()
    return {"status": "skipped"}


@router.post("/{catalog_id}/ml-groups/{group_id}/delete")
def delete_ml_group(catalog_id: str, group_id: str):
    now = datetime.utcnow().isoformat()
    with get_db_context() as db:
        db.execute(
            sa_text(
                "UPDATE ml_groups SET status = 'deleted', reviewed_at = :now"
                " WHERE id = CAST(:id AS uuid) AND catalog_id = CAST(:cid AS uuid)"
            ),
            {"now": now, "id": group_id, "cid": catalog_id},
        )
        db.commit()
    return {"status": "deleted"}


@router.post("/{catalog_id}/ml-groups/{group_id}/merge")
def merge_ml_group(catalog_id: str, group_id: str, body: dict):
    """Merge this group's images into an existing folk tag."""
    target_tag_id = body.get("tag_id")
    if not target_tag_id:
        raise HTTPException(status_code=400, detail="tag_id required")
    now = datetime.utcnow().isoformat()
    with get_db_context() as db:
        images = db.execute(
            sa_text(
                "SELECT image_id FROM ml_group_images"
                " WHERE group_id = CAST(:gid AS uuid)"
            ),
            {"gid": group_id},
        ).fetchall()
        for (image_id,) in images:
            db.execute(
                sa_text(
                    "INSERT INTO folk_image_tags (image_id, tag_id, source, annotated_at)"
                    " VALUES (:iid, CAST(:tid AS uuid), 'ml_confirmed', :now)"
                    " ON CONFLICT DO NOTHING"
                ),
                {"iid": image_id, "tid": target_tag_id, "now": now},
            )
        db.execute(
            sa_text(
                "UPDATE ml_groups SET status = 'merged', reviewed_at = :now"
                " WHERE id = CAST(:id AS uuid)"
            ),
            {"now": now, "id": group_id},
        )
        db.commit()
    return {"merged": len(images), "into_tag_id": target_tag_id}


# ---------------------------------------------------------------------------
# Home screen
# ---------------------------------------------------------------------------


@router.get("/{catalog_id}/home")
def home_screen(catalog_id: str):
    """Home screen data — what needs attention and recent folk-tag activity."""
    with get_db_context() as db:
        pending_groups = db.execute(
            sa_text(
                "SELECT COUNT(*), COALESCE(SUM(image_count), 0)"
                " FROM ml_groups"
                " WHERE catalog_id = CAST(:cid AS uuid) AND status = 'pending'"
            ),
            {"cid": catalog_id},
        ).first()

        untagged_count = db.execute(
            sa_text(
                "SELECT COUNT(*) FROM images i"
                " WHERE i.catalog_id = CAST(:cid AS uuid)"
                " AND NOT EXISTS ("
                "   SELECT 1 FROM folk_image_tags fi WHERE fi.image_id = i.id"
                " )"
            ),
            {"cid": catalog_id},
        ).scalar()

        pending_suggestions = db.execute(
            sa_text(
                "SELECT COUNT(*) FROM annotation_suggestions s"
                " JOIN images i ON i.id = s.image_id"
                " WHERE i.catalog_id = CAST(:cid AS uuid) AND s.status = 'pending'"
            ),
            {"cid": catalog_id},
        ).scalar()

        recent_tags = db.execute(
            sa_text(
                "SELECT t.id, t.label, t.created_at,"
                " COUNT(fi.image_id) AS image_count"
                " FROM folk_tags t"
                " LEFT JOIN folk_image_tags fi ON fi.tag_id = t.id"
                " WHERE t.catalog_id = CAST(:cid AS uuid)"
                " GROUP BY t.id"
                " ORDER BY t.created_at DESC LIMIT 10"
            ),
            {"cid": catalog_id},
        ).fetchall()

    needs_attention = []
    if pending_groups and pending_groups[0] > 0:
        needs_attention.append(
            {
                "type": "ml_groups",
                "label": (
                    f"{pending_groups[0]} unnamed group"
                    f"{'s' if pending_groups[0] != 1 else ''} found"
                ),
                "count": pending_groups[0],
                "image_count": int(pending_groups[1]),
                "action": "curate",
            }
        )
    if untagged_count and untagged_count > 0:
        needs_attention.append(
            {
                "type": "untagged",
                "label": f"{untagged_count:,} images have no tags",
                "count": untagged_count,
                "action": "browse_untagged",
            }
        )
    if pending_suggestions and pending_suggestions > 0:
        needs_attention.append(
            {
                "type": "suggestions",
                "label": f"{pending_suggestions} ML suggestions waiting for review",
                "count": pending_suggestions,
                "action": "review_suggestions",
            }
        )

    return {
        "needs_attention": needs_attention,
        "recent_tags": [
            {
                "id": str(r[0]),
                "label": r[1],
                "created_at": r[2].isoformat() if r[2] else None,
                "image_count": r[3],
            }
            for r in recent_tags
        ],
    }
