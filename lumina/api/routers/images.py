"""Unified images API router.

Handles all image operations for the UI:
- Listing and filtering images
- Thumbnail serving
- Full image serving
- Metadata retrieval
- Rating and tagging
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db import get_db
from ...db.repositories.image import ImageRepository


class ImageResponse(BaseModel):
    """Response model for image data."""

    id: str
    catalog_id: uuid.UUID
    source_path: str
    file_type: str
    checksum: str
    size_bytes: Optional[int] = None
    dates: Dict[str, Any] = {}
    metadata: Dict[str, Any] = {}
    thumbnail_path: Optional[str] = None
    dhash: Optional[str] = None
    ahash: Optional[str] = None
    whash: Optional[str] = None
    geohash_4: Optional[str] = None
    geohash_6: Optional[str] = None
    geohash_8: Optional[str] = None
    quality_score: Optional[int] = None
    status_id: str = "active"
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


router = APIRouter(prefix="/images", tags=["images"])


def _image_to_response(image: Any) -> ImageResponse:
    """Convert SQLAlchemy Image to response model."""
    return ImageResponse(
        id=image.id,
        catalog_id=image.catalog_id,
        source_path=image.source_path,
        file_type=image.file_type,
        checksum=image.checksum,
        size_bytes=image.size_bytes,
        dates=image.dates or {},
        metadata=image.metadata_json or {},
        thumbnail_path=image.thumbnail_path,
        dhash=image.dhash,
        ahash=image.ahash,
        whash=image.whash,
        geohash_4=image.geohash_4,
        geohash_6=image.geohash_6,
        geohash_8=image.geohash_8,
        quality_score=image.quality_score,
        status_id=image.status_id,
        description=image.description,
        created_at=image.created_at,
        updated_at=image.updated_at,
    )


@router.get("", response_model=List[ImageResponse])
def list_images(
    catalog_id: uuid.UUID,
    status: Optional[str] = None,
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db),
) -> List[ImageResponse]:
    """List images in a catalog with filtering."""
    repo = ImageRepository(session)
    images = repo.get_by_catalog(
        catalog_id=catalog_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [_image_to_response(img) for img in images]


@router.get("/{image_id}", response_model=ImageResponse)
def get_image(
    image_id: str,
    session: Session = Depends(get_db),
) -> ImageResponse:
    """Get a single image by ID."""
    repo = ImageRepository(session)
    image = repo.get(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    return _image_to_response(image)


@router.get("/{image_id}/thumbnail")
def get_thumbnail(
    image_id: str,
    size: str = Query("medium", pattern="^(small|medium|large)$"),
    session: Session = Depends(get_db),
) -> FileResponse:
    """Get image thumbnail."""
    repo = ImageRepository(session)
    image = repo.get(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    if not image.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not available")

    return FileResponse(
        image.thumbnail_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{image_id}/full")
def get_full_image(
    image_id: str,
    session: Session = Depends(get_db),
) -> FileResponse:
    """Get full-size image."""
    repo = ImageRepository(session)
    image = repo.get(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    # Determine media type from extension
    path = image.source_path.lower()
    if path.endswith(".png"):
        media_type = "image/png"
    elif path.endswith((".jpg", ".jpeg")):
        media_type = "image/jpeg"
    elif path.endswith(".heic"):
        media_type = "image/heic"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        image.source_path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.patch("/{image_id}")
def update_image(
    image_id: str,
    rating: Optional[int] = Query(None, ge=0, le=5),
    session: Session = Depends(get_db),
) -> dict:
    """Update image properties (rating, etc.)."""
    repo = ImageRepository(session)
    image = repo.get(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    if rating is not None:
        image.quality_score = rating * 20  # Convert 0-5 to 0-100

    repo.update(image)
    repo.commit()
    return {"status": "updated"}
