"""Base model and mixins for SQLModel."""

from datetime import datetime

from sqlmodel import Field, SQLModel


class TimestampMixin(SQLModel):
    """Mixin for created_at/updated_at timestamps."""

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BaseModel(SQLModel):
    """Base for all Lumina models with common config."""

    class Config:
        arbitrary_types_allowed = True
