"""Image repository for data access."""

import uuid
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from lumina.models.image import Image

from .base import BaseRepository


class ImageRepository(BaseRepository[Image]):
    """Repository for Image operations."""

    def __init__(self, session: Session):
        """Initialize image repository.

        Args:
            session: SQLModel database session
        """
        super().__init__(session, Image)

    def get_by_catalog(
        self,
        catalog_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> List[Image]:
        """Get images in a catalog.

        Args:
            catalog_id: Catalog UUID
            limit: Maximum number of images
            offset: Number of images to skip
            status: Optional processing status filter

        Returns:
            List of images
        """
        stmt = select(Image).where(Image.catalog_id == catalog_id)
        if status:
            stmt = stmt.where(Image.status == status)
        stmt = stmt.offset(offset).limit(limit)
        return list(self.session.exec(stmt).all())

    def get_without_hashes(self, catalog_id: uuid.UUID) -> List[str]:
        """Get image IDs that need hash computation.

        Args:
            catalog_id: Catalog UUID

        Returns:
            List of image IDs without hashes
        """
        stmt = (
            select(Image.id)
            .where(Image.catalog_id == catalog_id)
            .where(Image.dhash.is_(None))
        )
        return list(self.session.exec(stmt).all())

    def get_with_hashes(self, catalog_id: uuid.UUID) -> List[Dict[str, Any]]:
        """Get images with their hashes for duplicate detection.

        Args:
            catalog_id: Catalog UUID

        Returns:
            List of dicts with id, checksum, hashes, quality_score, size_bytes
        """
        stmt = (
            select(Image)
            .where(Image.catalog_id == catalog_id)
            .where(Image.dhash.isnot(None))
        )
        images = self.session.exec(stmt).all()
        return [
            {
                "id": img.id,
                "checksum": img.checksum,
                "dhash": img.dhash,
                "ahash": img.ahash,
                "whash": img.whash,
                "quality_score": img.quality_score,
                "size_bytes": img.size_bytes,
            }
            for img in images
        ]

    def get_with_timestamps(self, catalog_id: uuid.UUID) -> List[Dict[str, Any]]:
        """Get images with timestamps for burst detection.

        Args:
            catalog_id: Catalog UUID

        Returns:
            List of dicts with id, timestamp, camera, quality_score
        """
        stmt = select(Image).where(Image.catalog_id == catalog_id)
        images = self.session.exec(stmt).all()

        results = []
        for img in images:
            dates = img.dates or {}
            metadata = img.metadata_json or {}

            camera_make = metadata.get("camera_make", "")
            camera_model = metadata.get("camera_model", "")
            camera = f"{camera_make} {camera_model}".strip() or None

            results.append(
                {
                    "id": img.id,
                    "timestamp": dates.get("selected_date"),
                    "camera": camera,
                    "quality_score": img.quality_score,
                }
            )
        return results

    def update_hashes(
        self,
        image_id: str,
        dhash: str,
        ahash: str,
        whash: str,
    ) -> None:
        """Update image hashes.

        Args:
            image_id: Image ID
            dhash: Difference hash
            ahash: Average hash
            whash: Wavelet hash
        """
        image = self.get(image_id)
        if image:
            image.dhash = dhash
            image.ahash = ahash
            image.whash = whash
            self.update(image)
