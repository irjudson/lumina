"""
Helper module for storing image tags in the database.

This module is separate from tasks.py to avoid Celery dependencies.
"""

import logging
from typing import List

from sqlalchemy import text

from ..db import CatalogDB as CatalogDatabase

logger = logging.getLogger(__name__)


def store_image_tags(
    db: CatalogDatabase,
    catalog_id: str,
    image_id: str,
    tags: List,
    source: str,
) -> int:
    """Store tags for an image in the proper relational schema.

    Creates Tag entries if they don't exist, then creates ImageTag entries
    linking the image to its tags.

    Args:
        db: CatalogDatabase session
        catalog_id: The catalog UUID
        image_id: The image ID
        tags: List of TagResult objects with tag_name, confidence, category, source,
              openclip_confidence, and ollama_confidence attributes
        source: The tagging source ('openclip', 'ollama', or 'combined')

    Returns:
        Number of tags stored
    """
    if not tags:
        return 0

    stored_count = 0

    for tag in tags:
        try:
            # Get category as string (handle enum or string)
            category = getattr(tag, "category", None)
            if category is not None and hasattr(category, "value"):
                category = category.value  # Convert enum to string

            # Get or create tag in the tags table
            assert db.session is not None
            result = db.session.execute(
                text(
                    """
                    INSERT INTO tags (catalog_id, name, category, created_at)
                    VALUES (:catalog_id, :name, :category, NOW())
                    ON CONFLICT (catalog_id, name) DO UPDATE SET catalog_id = tags.catalog_id
                    RETURNING id
                """
                ),
                {
                    "catalog_id": catalog_id,
                    "name": tag.tag_name,
                    "category": category,
                },
            )
            tag_id = result.scalar()

            # Insert or update image_tag relationship
            assert db.session is not None
            db.session.execute(
                text(
                    """
                    INSERT INTO image_tags (image_id, tag_id, confidence, source,
                                           openclip_confidence, ollama_confidence, created_at)
                    VALUES (:image_id, :tag_id, :confidence, :source,
                            :openclip_confidence, :ollama_confidence, NOW())
                    ON CONFLICT (image_id, tag_id) DO UPDATE SET
                        confidence = :confidence,
                        source = :source,
                        openclip_confidence = COALESCE(:openclip_confidence, image_tags.openclip_confidence),
                        ollama_confidence = COALESCE(:ollama_confidence, image_tags.ollama_confidence)
                """
                ),
                {
                    "image_id": image_id,
                    "tag_id": tag_id,
                    "confidence": tag.confidence,
                    "source": getattr(tag, "source", source),
                    "openclip_confidence": getattr(tag, "openclip_confidence", None),
                    "ollama_confidence": getattr(tag, "ollama_confidence", None),
                },
            )
            stored_count += 1
        except Exception as e:
            logger.warning(
                f"Failed to store tag {tag.tag_name} for image {image_id}: {e}"
            )
            # Rollback to clear the failed transaction state
            if db.session:
                db.session.rollback()

    return stored_count
