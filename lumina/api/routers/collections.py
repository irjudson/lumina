"""Collections API router.

CRUD operations for user-created photo collections and system-managed categories.
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
    source: str
    system_key: Optional[str] = None
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


# --- Endpoints ---


@router.get("/{catalog_id}/collections", response_model=List[CollectionListItem])
def list_collections(
    catalog_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> List[CollectionListItem]:
    """List all collections in a catalog with image counts."""
    _get_catalog_or_404(db, catalog_id)

    results = (
        db.query(
            Collection,
            func.count(CollectionImage.id).label("image_count"),
            func.sum(
                case((CollectionImage.confirmed == False, 1), else_=0)  # noqa: E712
            ).label("pending_count"),
        )
        .outerjoin(CollectionImage, CollectionImage.collection_id == Collection.id)
        .filter(Collection.catalog_id == catalog_id)
        .group_by(Collection.id)
        .order_by(Collection.source.desc(), Collection.updated_at.desc())
        .all()
    )

    items = []
    for c, count, pending in results:
        items.append(
            CollectionListItem(
                id=str(c.id),
                name=c.name,
                description=c.description,
                cover_image_id=c.cover_image_id,
                image_count=count,
                pending_count=int(pending or 0),
                source=c.source,
                system_key=c.system_key,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
        )
    return items


@router.post("/{catalog_id}/collections", response_model=CollectionDetail)
def create_collection(
    catalog_id: uuid.UUID,
    request: CreateCollectionRequest,
    db: Session = Depends(get_db),
) -> CollectionDetail:
    """Create a new user collection."""
    _get_catalog_or_404(db, catalog_id)

    collection = Collection(
        catalog_id=catalog_id,
        name=request.name,
        description=request.description,
        source="user",
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
        created_at=collection.created_at,
        updated_at=collection.updated_at,
    )


@router.delete("/{catalog_id}/collections/{collection_id}")
def delete_collection(
    catalog_id: uuid.UUID,
    collection_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    """Delete a collection (does not delete images). System collections cannot be deleted."""
    collection = _get_collection_or_404(db, catalog_id, collection_id)
    if collection.source == "system":
        raise HTTPException(
            status_code=409,
            detail="System collections cannot be deleted. Clear their images instead.",
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
    """Confirm AI-suggested memberships for a system collection."""
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
