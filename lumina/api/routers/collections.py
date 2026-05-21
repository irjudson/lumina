"""Collections API router.

CRUD for user-created photo collections and system-managed categories.
Supports a 2-level hierarchy: top-level categories → sub-collections (trips, buckets, etc.)
"""

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ...db import get_db
from ...db.models import Catalog, Collection, CollectionImage, Image

router = APIRouter()


# --- Pydantic Models ---


class CreateCollectionRequest(BaseModel):
    name: str
    description: Optional[str] = None
    parent_id: Optional[str] = None


class UpdateCollectionRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cover_image_id: Optional[str] = None


class CollectionListItem(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    cover_image_id: Optional[str] = None
    image_count: int
    pending_count: int
    child_count: int
    source: str
    system_key: Optional[str] = None
    parent_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CollectionDetail(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    cover_image_id: Optional[str] = None
    image_ids: List[str]
    source: str
    system_key: Optional[str] = None
    parent_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AddImagesRequest(BaseModel):
    image_ids: List[str]


class RemoveImagesRequest(BaseModel):
    image_ids: List[str]


class ConfirmMembershipsRequest(BaseModel):
    image_ids: List[str]


class RejectMembershipsRequest(BaseModel):
    image_ids: List[str]


# --- Helpers ---


def _get_catalog_or_404(db: Session, catalog_id: uuid.UUID) -> Catalog:
    catalog = db.query(Catalog).filter(Catalog.id == catalog_id).first()
    if not catalog:
        raise HTTPException(status_code=404, detail="Catalog not found")
    return catalog


def _get_collection_or_404(
    db: Session, catalog_id: uuid.UUID, collection_id: uuid.UUID
) -> Collection:
    collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.catalog_id == catalog_id)
        .first()
    )
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection


def _child_counts(db: Session, catalog_id: uuid.UUID) -> dict:
    """Return {parent_id_str: child_count} for all collections in catalog."""
    rows = (
        db.query(Collection.parent_id, func.count(Collection.id))
        .filter(Collection.catalog_id == catalog_id, Collection.parent_id.isnot(None))
        .group_by(Collection.parent_id)
        .all()
    )
    return {str(row[0]): row[1] for row in rows}


# --- Endpoints ---


@router.get("/{catalog_id}/collections", response_model=List[CollectionListItem])
def list_collections(
    catalog_id: uuid.UUID,
    parent_id: Optional[str] = None,
    db: Session = Depends(get_db),
) -> List[CollectionListItem]:
    """List collections. Use ?parent_id=<uuid> to list children, omit for top-level only."""
    _get_catalog_or_404(db, catalog_id)

    counts = _child_counts(db, catalog_id)

    q = (
        db.query(
            Collection,
            func.count(CollectionImage.id).label("image_count"),
            func.sum(
                case((CollectionImage.confirmed == False, 1), else_=0)  # noqa: E712
            ).label("pending_count"),
        )
        .outerjoin(CollectionImage, CollectionImage.collection_id == Collection.id)
        .filter(Collection.catalog_id == catalog_id)
    )

    if parent_id is not None:
        q = q.filter(Collection.parent_id == uuid.UUID(parent_id))
    else:
        q = q.filter(Collection.parent_id.is_(None))

    results = (
        q.group_by(Collection.id)
        .order_by(Collection.source.desc(), Collection.updated_at.desc())
        .all()
    )

    return [
        CollectionListItem(
            id=str(c.id),
            name=c.name,
            description=c.description,
            cover_image_id=c.cover_image_id,
            image_count=count,
            pending_count=int(pending or 0),
            child_count=counts.get(str(c.id), 0),
            source=c.source,
            system_key=c.system_key,
            parent_id=str(c.parent_id) if c.parent_id else None,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c, count, pending in results
    ]


@router.post("/{catalog_id}/collections", response_model=CollectionDetail)
def create_collection(
    catalog_id: uuid.UUID,
    request: CreateCollectionRequest,
    db: Session = Depends(get_db),
) -> CollectionDetail:
    """Create a new user collection. Optionally specify parent_id for a sub-collection."""
    _get_catalog_or_404(db, catalog_id)

    parent_uuid = None
    if request.parent_id:
        parent = _get_collection_or_404(db, catalog_id, uuid.UUID(request.parent_id))
        if parent.parent_id is not None:
            raise HTTPException(
                status_code=400, detail="Collections are limited to 2 levels deep."
            )
        parent_uuid = parent.id

    collection = Collection(
        catalog_id=catalog_id,
        name=request.name,
        description=request.description,
        source="user",
        parent_id=parent_uuid,
    )
    db.add(collection)
    db.commit()
    db.refresh(collection)

    return CollectionDetail(
        id=str(collection.id),
        name=collection.name,
        description=collection.description,
        cover_image_id=collection.cover_image_id,
        image_ids=[],
        source=collection.source,
        system_key=collection.system_key,
        parent_id=str(collection.parent_id) if collection.parent_id else None,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
    )


@router.get(
    "/{catalog_id}/collections/{collection_id}", response_model=CollectionDetail
)
def get_collection(
    catalog_id: uuid.UUID,
    collection_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> CollectionDetail:
    """Get a collection with its confirmed image IDs."""
    collection = _get_collection_or_404(db, catalog_id, collection_id)

    image_ids = [
        ci.image_id
        for ci in db.query(CollectionImage)
        .filter(
            CollectionImage.collection_id == collection_id,
            CollectionImage.confirmed == True,  # noqa: E712
        )
        .order_by(CollectionImage.position, CollectionImage.added_at)
        .all()
    ]

    return CollectionDetail(
        id=str(collection.id),
        name=collection.name,
        description=collection.description,
        cover_image_id=collection.cover_image_id,
        image_ids=image_ids,
        source=collection.source,
        system_key=collection.system_key,
        parent_id=str(collection.parent_id) if collection.parent_id else None,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
    )


@router.put(
    "/{catalog_id}/collections/{collection_id}", response_model=CollectionDetail
)
def update_collection(
    catalog_id: uuid.UUID,
    collection_id: uuid.UUID,
    request: UpdateCollectionRequest,
    db: Session = Depends(get_db),
) -> CollectionDetail:
    """Update collection name, description, or cover image."""
    collection = _get_collection_or_404(db, catalog_id, collection_id)

    if request.name is not None:
        collection.name = request.name
    if request.description is not None:
        collection.description = request.description
    if request.cover_image_id is not None:
        collection.cover_image_id = request.cover_image_id

    collection.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(collection)

    image_ids = [
        ci.image_id
        for ci in db.query(CollectionImage)
        .filter(
            CollectionImage.collection_id == collection_id,
            CollectionImage.confirmed == True,  # noqa: E712
        )
        .order_by(CollectionImage.position, CollectionImage.added_at)
        .all()
    ]

    return CollectionDetail(
        id=str(collection.id),
        name=collection.name,
        description=collection.description,
        cover_image_id=collection.cover_image_id,
        image_ids=image_ids,
        source=collection.source,
        system_key=collection.system_key,
        parent_id=str(collection.parent_id) if collection.parent_id else None,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
    )


@router.delete("/{catalog_id}/collections/{collection_id}")
def delete_collection(
    catalog_id: uuid.UUID,
    collection_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    """Delete a collection. Top-level system categories cannot be deleted."""
    collection = _get_collection_or_404(db, catalog_id, collection_id)
    if collection.source == "system" and collection.parent_id is None:
        raise HTTPException(
            status_code=409,
            detail="Top-level system categories cannot be deleted.",
        )
    db.delete(collection)
    db.commit()
    return {"status": "deleted"}


@router.post("/{catalog_id}/collections/{collection_id}/images")
def add_images_to_collection(
    catalog_id: uuid.UUID,
    collection_id: uuid.UUID,
    request: AddImagesRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Add images to a collection."""
    collection = _get_collection_or_404(db, catalog_id, collection_id)

    max_pos = (
        db.query(func.max(CollectionImage.position))
        .filter(CollectionImage.collection_id == collection_id)
        .scalar()
        or 0
    )

    existing = set(
        ci.image_id
        for ci in db.query(CollectionImage.image_id)
        .filter(CollectionImage.collection_id == collection_id)
        .all()
    )

    added = 0
    for image_id in request.image_ids:
        if image_id in existing:
            continue
        image = (
            db.query(Image)
            .filter(Image.id == image_id, Image.catalog_id == catalog_id)
            .first()
        )
        if not image:
            continue
        max_pos += 1
        db.add(
            CollectionImage(
                collection_id=collection_id,
                image_id=image_id,
                position=max_pos,
                source="user",
                confirmed=True,
                confidence=1.0,
            )
        )
        added += 1

    if not collection.cover_image_id and request.image_ids:
        collection.cover_image_id = request.image_ids[0]

    collection.updated_at = datetime.utcnow()
    db.commit()

    return {"added": added}


@router.delete("/{catalog_id}/collections/{collection_id}/images")
def remove_images_from_collection(
    catalog_id: uuid.UUID,
    collection_id: uuid.UUID,
    request: RemoveImagesRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Remove images from a collection."""
    collection = _get_collection_or_404(db, catalog_id, collection_id)

    removed = (
        db.query(CollectionImage)
        .filter(
            CollectionImage.collection_id == collection_id,
            CollectionImage.image_id.in_(request.image_ids),
        )
        .delete(synchronize_session=False)
    )

    if collection.cover_image_id in request.image_ids:
        first = (
            db.query(CollectionImage)
            .filter(
                CollectionImage.collection_id == collection_id,
                CollectionImage.confirmed == True,  # noqa: E712
            )
            .order_by(CollectionImage.position)
            .first()
        )
        collection.cover_image_id = first.image_id if first else None

    collection.updated_at = datetime.utcnow()
    db.commit()

    return {"removed": removed}


@router.post("/{catalog_id}/collections/{collection_id}/confirm")
def confirm_memberships(
    catalog_id: uuid.UUID,
    collection_id: uuid.UUID,
    request: ConfirmMembershipsRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Confirm AI-suggested memberships."""
    _get_collection_or_404(db, catalog_id, collection_id)

    updated = (
        db.query(CollectionImage)
        .filter(
            CollectionImage.collection_id == collection_id,
            CollectionImage.image_id.in_(request.image_ids),
            CollectionImage.confirmed == False,  # noqa: E712
        )
        .all()
    )
    for ci in updated:
        ci.confirmed = True

    db.commit()
    return {"confirmed": len(updated)}


@router.post("/{catalog_id}/collections/{collection_id}/reject")
def reject_memberships(
    catalog_id: uuid.UUID,
    collection_id: uuid.UUID,
    request: RejectMembershipsRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Reject AI-suggested memberships, removing them from the collection."""
    _get_collection_or_404(db, catalog_id, collection_id)

    removed = (
        db.query(CollectionImage)
        .filter(
            CollectionImage.collection_id == collection_id,
            CollectionImage.image_id.in_(request.image_ids),
            CollectionImage.confirmed == False,  # noqa: E712
        )
        .delete(synchronize_session=False)
    )

    db.commit()
    return {"rejected": removed}
