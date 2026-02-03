"""Tag models - tracks tags and image-tag associations."""

import uuid as uuid_module
from datetime import datetime
from enum import Enum
from typing import List, Optional

from sqlalchemy import Column, ForeignKey, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlmodel import Field, SQLModel


class TagSource(str, Enum):
    """Source of tag assignment."""

    MANUAL = "manual"
    OPENCLIP = "openclip"
    OLLAMA = "ollama"
    COMBINED = "combined"


class Tag(SQLModel, table=True):
    """Tag database model - categorization tags for images."""

    __tablename__ = "tags"

    id: int = Field(default=None, primary_key=True)
    catalog_id: uuid_module.UUID = Field(
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("catalogs.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    name: str
    category: Optional[str] = None
    parent_id: Optional[int] = Field(default=None, foreign_key="tags.id")
    synonyms: List[str] = Field(default_factory=list, sa_column=Column(ARRAY(Text)))
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ImageTag(SQLModel, table=True):
    """ImageTag database model - links images to tags with confidence scores."""

    __tablename__ = "image_tags"

    image_id: str = Field(foreign_key="images.id", primary_key=True)
    tag_id: int = Field(foreign_key="tags.id", primary_key=True)
    confidence: float = 1.0
    source: TagSource = TagSource.MANUAL
    openclip_confidence: Optional[float] = None
    ollama_confidence: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
