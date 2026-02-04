"""Burst model - represents a group of rapidly captured images."""

import uuid as uuid_module
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlmodel import Field, SQLModel


class Burst(SQLModel, table=True):
    """Burst database model - tracks groups of burst-mode images."""

    __tablename__ = "bursts"

    id: uuid_module.UUID = Field(
        default_factory=uuid_module.uuid4,
        primary_key=True,
    )
    catalog_id: uuid_module.UUID = Field(
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("catalogs.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    image_count: int
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    camera_make: Optional[str] = Field(default=None, max_length=255)
    camera_model: Optional[str] = Field(default=None, max_length=255)
    best_image_id: Optional[str] = None
    selection_method: str = Field(default="quality", max_length=50)
    created_at: datetime = Field(default_factory=datetime.utcnow)
