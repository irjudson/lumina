"""Base repository pattern for data access."""

from typing import Any, Generic, List, Optional, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Generic repository with CRUD operations.

    Works with both SQLAlchemy and SQLModel models.
    """

    def __init__(self, session: Session, model: Type[T]):
        """Initialize repository with session and model type.

        Args:
            session: Database session (SQLAlchemy or SQLModel compatible)
            model: The model class this repository operates on
        """
        self.session: Any = session  # Any to support both SQLModel and SQLAlchemy
        self.model = model

    def get(self, id: str) -> Optional[T]:
        """Get entity by ID.

        Args:
            id: The entity's primary key

        Returns:
            Entity if found, None otherwise
        """
        return self.session.get(self.model, id)

    def list(self, limit: int = 100, offset: int = 0) -> List[T]:
        """List entities with pagination.

        Args:
            limit: Maximum number of entities to return
            offset: Number of entities to skip

        Returns:
            List of entities
        """
        stmt = select(self.model).offset(offset).limit(limit)
        result = self.session.execute(stmt)
        return list(result.scalars().all())

    def add(self, entity: T) -> T:
        """Add new entity.

        Args:
            entity: Entity to add

        Returns:
            Added entity
        """
        self.session.add(entity)
        self.session.flush()
        return entity

    def update(self, entity: T) -> T:
        """Update existing entity.

        Args:
            entity: Entity to update

        Returns:
            Updated entity
        """
        self.session.add(entity)
        self.session.flush()
        return entity

    def delete(self, entity: T) -> None:
        """Delete entity.

        Args:
            entity: Entity to delete
        """
        self.session.delete(entity)
        self.session.flush()

    def commit(self) -> None:
        """Commit transaction."""
        self.session.commit()

    def rollback(self) -> None:
        """Rollback transaction."""
        self.session.rollback()
