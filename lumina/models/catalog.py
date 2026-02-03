"""Catalog model - represents a photo library."""

import uuid as uuid_module
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Column, Field, SQLModel


class CatalogBase(SQLModel):
    """Shared catalog fields."""

    name: str = Field(max_length=255)
    source_directories: List[str] = Field(sa_column=Column(ARRAY(Text)))
    organized_directory: Optional[str] = None


class Catalog(CatalogBase, table=True):
    """Catalog database model."""

    __tablename__ = "catalogs"

    id: uuid_module.UUID = Field(
        default_factory=uuid_module.uuid4,
        primary_key=True,
    )
    schema_name: str = Field(max_length=255, unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CatalogCreate(CatalogBase):
    """Schema for creating a catalog."""

    pass


class CatalogRead(CatalogBase):
    """Schema for reading a catalog."""

    id: uuid_module.UUID
    schema_name: str
    created_at: datetime
    updated_at: datetime
