"""Database repositories for data access."""

from .base import BaseRepository
from .image import ImageRepository

__all__ = ["BaseRepository", "ImageRepository"]
