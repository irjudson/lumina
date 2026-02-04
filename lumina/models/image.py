"""Image model - represents an image/video in a catalog."""

import uuid as uuid_module
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel

from .base import TimestampMixin


class ProcessingStatus(str, Enum):
    """Processing status for images."""

    pending = "pending"
    scanning = "scanning"
    hashing = "hashing"
    tagging = "tagging"
    complete = "complete"
    failed = "failed"


class FileType(str, Enum):
    """File type for images/videos."""

    image = "image"
    video = "video"


class ImageBase(SQLModel):
    """Shared image fields."""

    source_path: str
    file_type: FileType = FileType.image
    checksum: str
    size_bytes: Optional[int] = None
    dates: dict = Field(default_factory=dict, sa_column=Column(JSONB, default={}))
    metadata_json: dict = Field(
        default_factory=dict, sa_column=Column("metadata", JSONB, default={})
    )
    thumbnail_path: Optional[str] = None
    dhash: Optional[str] = None
    ahash: Optional[str] = None
    whash: Optional[str] = None
    geohash_4: Optional[str] = None
    geohash_6: Optional[str] = None
    geohash_8: Optional[str] = None
    quality_score: Optional[int] = None
    status: str = "active"
    processing_flags: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, default={})
    )
    clip_embedding: Optional[List[float]] = Field(
        default=None, sa_column=Column(Vector(768))
    )
    description: Optional[str] = None
    edit_data: Optional[dict] = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )


class Image(ImageBase, TimestampMixin, table=True):
    """Image database model."""

    __tablename__ = "images"

    id: str = Field(primary_key=True)
    catalog_id: uuid_module.UUID = Field(foreign_key="catalogs.id")
    burst_id: Optional[uuid_module.UUID] = Field(default=None, foreign_key="bursts.id")
    burst_sequence: Optional[int] = None


class ImageRead(ImageBase):
    """Schema for reading an image."""

    id: str
    catalog_id: uuid_module.UUID
    created_at: datetime
    updated_at: datetime
