"""Collections API router.

CRUD operations for user-created photo collections (albums).
"""

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
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
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AddImagesRequest(BaseModel):
    image_ids: List[str]


class RemoveImagesRequest(BaseModel):
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
        )
        .outerjoin(CollectionImage, CollectionImage.collection_id == Collection.id)
        .filter(Collection.catalog_id == catalog_id)
        .group_by(Collection.id)
        .order_by(Collection.updated_at.desc())
        .all()
    )

    return [
        CollectionListItem(
            id=str(c.id),
            name=c.name,
            description=c.description,
            cover_image_id=c.cover_image_id,
            image_count=count,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c, count in results
    ]


@router.post("/{catalog_id}/collections", response_model=CollectionDetail)
def create_collection(
    catalog_id: uuid.UUID,
    request: CreateCollectionRequest,
    db: Session = Depends(get_db),
) -> CollectionDetail:
    """Create a new collection."""
    _get_catalog_or_404(db, catalog_id)

    collection = Collection(
        catalog_id=catalog_id,
        name=request.name,
        description=request.description,
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
    """Get a collection with its image IDs."""
    collection = _get_collection_or_404(db, catalog_id, collection_id)

    image_ids = [
        ci.image_id
        for ci in db.query(CollectionImage)
        .filter(CollectionImage.collection_id == collection_id)
        .order_by(CollectionImage.position, CollectionImage.added_at)
        .all()
    ]

    return CollectionDetail(
        id=str(collection.id),
        name=collection.name,
        description=collection.description,
        cover_image_id=collection.cover_image_id,
        image_ids=image_ids,
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
        .filter(CollectionImage.collection_id == collection_id)
        .order_by(CollectionImage.position, CollectionImage.added_at)
        .all()
    ]

    return CollectionDetail(
        id=str(collection.id),
        name=collection.name,
        description=collection.description,
        cover_image_id=collection.cover_image_id,
        image_ids=image_ids,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
    )


@router.delete("/{catalog_id}/collections/{collection_id}")
def delete_collection(
    catalog_id: uuid.UUID,
    collection_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    """Delete a collection (does not delete images)."""
    collection = _get_collection_or_404(db, catalog_id, collection_id)
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

    # Get current max position
    max_pos = (
        db.query(func.max(CollectionImage.position))
        .filter(CollectionImage.collection_id == collection_id)
        .scalar()
        or 0
    )

    # Get existing image IDs in the collection
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
        # Verify image exists in the catalog
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
            )
        )
        added += 1

    # Auto-set cover if none
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

    # Update cover if it was removed
    if collection.cover_image_id in request.image_ids:
        first = (
            db.query(CollectionImage)
            .filter(CollectionImage.collection_id == collection_id)
            .order_by(CollectionImage.position)
            .first()
        )
        collection.cover_image_id = first.image_id if first else None

    collection.updated_at = datetime.utcnow()
    db.commit()

    return {"removed": removed}
