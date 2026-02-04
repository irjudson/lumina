"""Duplicate models - tracks duplicate image groups and members."""

import uuid as uuid_module
from datetime import datetime
from enum import Enum

from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlmodel import Field, SQLModel


class SimilarityType(str, Enum):
    """Type of similarity detection used."""

    EXACT = "exact"
    PERCEPTUAL = "perceptual"


class DuplicateGroup(SQLModel, table=True):
    """DuplicateGroup database model - tracks groups of duplicate images."""

    __tablename__ = "duplicate_groups"

    id: int = Field(default=None, primary_key=True)
    catalog_id: uuid_module.UUID = Field(
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("catalogs.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    primary_image_id: str = Field(foreign_key="images.id")
    similarity_type: SimilarityType
    confidence: int  # 0-100
    reviewed: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DuplicateMember(SQLModel, table=True):
    """DuplicateMember database model - links images to duplicate groups."""

    __tablename__ = "duplicate_members"

    group_id: int = Field(foreign_key="duplicate_groups.id", primary_key=True)
    image_id: str = Field(foreign_key="images.id", primary_key=True)
    similarity_score: int  # 0-100
