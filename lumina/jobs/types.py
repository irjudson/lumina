"""Job system types and context."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..db import get_db_context
from ..db.models import Catalog


@dataclass
class JobContext:
    """Standardized context passed to all job functions.

    This provides a consistent interface for all job types and handles
    lazy loading of catalog data.
    """

    job_id: str
    catalog_id: str
    parameters: Dict[str, Any]

    # Cached values
    _catalog: Optional[Catalog] = None

    @property
    def catalog(self) -> Optional[Catalog]:
        """Get catalog from database (lazy loaded)."""
        if self._catalog is None:
            with get_db_context() as db:
                self._catalog = (
                    db.query(Catalog).filter(Catalog.id == self.catalog_id).first()
                )
        return self._catalog

    @property
    def source_paths(self) -> list[str]:
        """Get source directories from catalog."""
        if self.catalog and self.catalog.source_directories:
            return list(self.catalog.source_directories)  # type: ignore[arg-type]
        return []

    def get(self, key: str, default: Any = None) -> Any:
        """Get parameter value with optional default."""
        return self.parameters.get(key, default)
