# Lumina V2 Architecture Refactor

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce codebase from ~34,000 LOC to ~4,500 LOC by unifying models, creating a generic job framework, consolidating APIs, and extracting pure analysis functions.

**Architecture:**
- SQLModel for unified Pydantic+SQLAlchemy models
- Generic `ParallelJobExecutor` replacing 6 parallel_*.py files
- Pure function analysis modules (no embedded orchestration)
- Single consolidated API layer
- Repository pattern for data access

**Tech Stack:** SQLModel, FastAPI, PostgreSQL, pgvector, ThreadPoolExecutor

---

## Phase 1: Foundation - Unified Models with SQLModel

### Task 1.1: Install SQLModel and Create Base Models

**Files:**
- Create: `lumina/models/__init__.py`
- Create: `lumina/models/base.py`
- Modify: `pyproject.toml`

**Step 1: Add SQLModel dependency**

```toml
# In pyproject.toml dependencies array, add:
"sqlmodel>=0.0.14,<1.0.0",
```

**Step 2: Run to verify installation**

Run: `pip install -e ".[dev]"`
Expected: Success, sqlmodel installed

**Step 3: Create models directory and base**

```python
# lumina/models/__init__.py
"""Unified SQLModel definitions for Lumina."""

from .base import BaseModel, TimestampMixin
from .catalog import Catalog
from .image import Image, ImageStatus
from .job import Job, JobBatch
from .duplicate import DuplicateGroup, DuplicateMember
from .burst import Burst
from .tag import Tag, ImageTag

__all__ = [
    "BaseModel",
    "TimestampMixin",
    "Catalog",
    "Image",
    "ImageStatus",
    "Job",
    "JobBatch",
    "DuplicateGroup",
    "DuplicateMember",
    "Burst",
    "Tag",
    "ImageTag",
]
```

```python
# lumina/models/base.py
"""Base model and mixins for SQLModel."""

from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class TimestampMixin(SQLModel):
    """Mixin for created_at/updated_at timestamps."""

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BaseModel(SQLModel):
    """Base for all Lumina models with common config."""

    class Config:
        arbitrary_types_allowed = True
```

**Step 4: Run basic import test**

Run: `python -c "from lumina.models.base import BaseModel, TimestampMixin; print('OK')"`
Expected: OK

**Step 5: Commit**

```bash
git add lumina/models/ pyproject.toml
git commit -m "feat: add SQLModel foundation for unified models"
```

---

### Task 1.2: Create Catalog Model

**Files:**
- Create: `lumina/models/catalog.py`
- Test: `tests/models/test_catalog.py`

**Step 1: Write the failing test**

```python
# tests/models/test_catalog.py
"""Tests for Catalog model."""

import uuid
from lumina.models.catalog import Catalog, CatalogCreate


def test_catalog_create_generates_uuid():
    """Catalog should auto-generate UUID."""
    catalog = Catalog(
        name="Test Catalog",
        schema_name="cat_test",
        source_directories=["/photos"],
    )
    assert catalog.id is not None
    assert isinstance(catalog.id, uuid.UUID)


def test_catalog_create_schema():
    """CatalogCreate should validate input."""
    data = CatalogCreate(
        name="My Photos",
        source_directories=["/home/user/photos"],
    )
    assert data.name == "My Photos"
    assert data.source_directories == ["/home/user/photos"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/models/test_catalog.py -v`
Expected: FAIL with "No module named 'lumina.models.catalog'"

**Step 3: Write minimal implementation**

```python
# lumina/models/catalog.py
"""Catalog model - represents a photo library."""

import uuid as uuid_module
from datetime import datetime
from typing import List, Optional

from sqlmodel import SQLModel, Field, Column
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy import Text


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
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/models/test_catalog.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lumina/models/catalog.py tests/models/
git commit -m "feat: add Catalog SQLModel with create/read schemas"
```

---

### Task 1.3: Create Image Model

**Files:**
- Create: `lumina/models/image.py`
- Test: `tests/models/test_image.py`

**Step 1: Write the failing test**

```python
# tests/models/test_image.py
"""Tests for Image model."""

import uuid
from lumina.models.image import Image, ProcessingStatus


def test_image_defaults():
    """Image should have sensible defaults."""
    image = Image(
        id="abc123",
        catalog_id=uuid.uuid4(),
        source_path="/photos/img.jpg",
        file_type="image",
        checksum="sha256:abc",
    )
    assert image.status == ProcessingStatus.PENDING
    assert image.processing_flags == {}
    assert image.quality_score is None


def test_processing_status_enum():
    """ProcessingStatus should have expected values."""
    assert ProcessingStatus.PENDING.value == "pending"
    assert ProcessingStatus.COMPLETE.value == "complete"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/models/test_image.py -v`
Expected: FAIL with import error

**Step 3: Write minimal implementation**

```python
# lumina/models/image.py
"""Image model - represents a photo or video in a catalog."""

import uuid as uuid_module
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pgvector.sqlalchemy import Vector
from sqlmodel import SQLModel, Field, Column, Relationship
from sqlalchemy import BigInteger, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID


class ProcessingStatus(str, Enum):
    """Processing pipeline status."""

    PENDING = "pending"
    ANALYZING = "analyzing"
    NEEDS_REVIEW = "needs_review"
    COMPLETE = "complete"


class FileType(str, Enum):
    """Type of media file."""

    IMAGE = "image"
    VIDEO = "video"


class ImageBase(SQLModel):
    """Shared image fields."""

    source_path: str
    file_type: str
    checksum: str
    size_bytes: Optional[int] = Field(default=None, sa_column=Column(BigInteger))

    # Metadata stored as JSON
    dates: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB))
    metadata_json: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB),
    )

    # Perceptual hashes
    dhash: Optional[str] = None
    ahash: Optional[str] = None
    whash: Optional[str] = None

    # Geohash for spatial queries
    geohash_4: Optional[str] = Field(default=None, max_length=4)
    geohash_6: Optional[str] = Field(default=None, max_length=6)
    geohash_8: Optional[str] = Field(default=None, max_length=8)

    # Analysis
    quality_score: Optional[int] = None
    thumbnail_path: Optional[str] = None
    description: Optional[str] = None


class Image(ImageBase, table=True):
    """Image database model."""

    __tablename__ = "images"

    id: str = Field(primary_key=True)
    catalog_id: uuid_module.UUID = Field(
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("catalogs.id", ondelete="CASCADE"),
            nullable=False,
        )
    )

    status: ProcessingStatus = Field(default=ProcessingStatus.PENDING)
    processing_flags: Dict[str, bool] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, server_default="{}"),
    )

    # Burst reference
    burst_id: Optional[uuid_module.UUID] = Field(
        default=None,
        sa_column=Column(UUID(as_uuid=True), ForeignKey("bursts.id", ondelete="SET NULL")),
    )
    burst_sequence: Optional[int] = None

    # Semantic search embedding
    clip_embedding: Optional[List[float]] = Field(
        default=None,
        sa_column=Column(Vector(768)),
    )

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ImageRead(ImageBase):
    """Schema for reading an image."""

    id: str
    catalog_id: uuid_module.UUID
    status: ProcessingStatus
    processing_flags: Dict[str, bool]
    created_at: datetime
    updated_at: datetime
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/models/test_image.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lumina/models/image.py tests/models/test_image.py
git commit -m "feat: add Image SQLModel with ProcessingStatus enum"
```

---

### Task 1.4: Create Job and JobBatch Models

**Files:**
- Create: `lumina/models/job.py`
- Test: `tests/models/test_job.py`

**Step 1: Write the failing test**

```python
# tests/models/test_job.py
"""Tests for Job and JobBatch models."""

import uuid
from lumina.models.job import Job, JobBatch, JobStatus, BatchStatus


def test_job_status_enum():
    """JobStatus should have standard states."""
    assert JobStatus.PENDING.value == "pending"
    assert JobStatus.RUNNING.value == "running"
    assert JobStatus.SUCCESS.value == "success"
    assert JobStatus.FAILED.value == "failed"


def test_job_creation():
    """Job should accept standard fields."""
    job = Job(
        id="job-123",
        catalog_id=uuid.uuid4(),
        job_type="scan",
        status=JobStatus.PENDING,
    )
    assert job.status == JobStatus.PENDING
    assert job.parameters == {}


def test_batch_status_transitions():
    """BatchStatus should have workflow states."""
    assert BatchStatus.PENDING.value == "pending"
    assert BatchStatus.RUNNING.value == "running"
    assert BatchStatus.COMPLETED.value == "completed"
    assert BatchStatus.FAILED.value == "failed"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/models/test_job.py -v`
Expected: FAIL with import error

**Step 3: Write minimal implementation**

```python
# lumina/models/job.py
"""Job and JobBatch models for background task tracking."""

import uuid as uuid_module
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlmodel import SQLModel, Field, Column
from sqlalchemy import Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID


class JobStatus(str, Enum):
    """Job execution status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BatchStatus(str, Enum):
    """Batch execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(SQLModel, table=True):
    """Background job tracking."""

    __tablename__ = "jobs"

    id: str = Field(primary_key=True)
    catalog_id: Optional[uuid_module.UUID] = Field(
        default=None,
        sa_column=Column(UUID(as_uuid=True), nullable=True),
    )
    job_type: str = Field(max_length=50)
    status: JobStatus = Field(default=JobStatus.PENDING)

    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB),
    )
    progress: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB),
    )
    result: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB),
    )
    error: Optional[str] = Field(default=None, sa_column=Column(Text))

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class JobBatch(SQLModel, table=True):
    """Batch within a parallel job."""

    __tablename__ = "job_batches"

    id: uuid_module.UUID = Field(
        default_factory=uuid_module.uuid4,
        primary_key=True,
    )
    parent_job_id: str = Field(foreign_key="jobs.id")
    catalog_id: uuid_module.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), nullable=False),
    )

    batch_number: int
    total_batches: int
    job_type: str = Field(max_length=50)
    status: BatchStatus = Field(default=BatchStatus.PENDING)

    work_items: List[Any] = Field(
        default_factory=list,
        sa_column=Column(JSONB),
    )
    items_count: int = 0

    worker_id: Optional[str] = None
    processed_count: int = 0
    success_count: int = 0
    error_count: int = 0

    results: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB),
    )
    error_message: Optional[str] = None

    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/models/test_job.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lumina/models/job.py tests/models/test_job.py
git commit -m "feat: add Job and JobBatch SQLModels"
```

---

### Task 1.5: Create Remaining Models (Burst, Duplicate, Tag)

**Files:**
- Create: `lumina/models/burst.py`
- Create: `lumina/models/duplicate.py`
- Create: `lumina/models/tag.py`
- Test: `tests/models/test_burst.py`
- Test: `tests/models/test_duplicate.py`
- Test: `tests/models/test_tag.py`

**Step 1: Write tests for Burst**

```python
# tests/models/test_burst.py
"""Tests for Burst model."""

import uuid
from datetime import datetime
from lumina.models.burst import Burst


def test_burst_creation():
    """Burst should track image sequences."""
    burst = Burst(
        catalog_id=uuid.uuid4(),
        image_count=5,
        start_time=datetime(2024, 1, 1, 12, 0, 0),
        end_time=datetime(2024, 1, 1, 12, 0, 3),
        duration_seconds=3.0,
    )
    assert burst.image_count == 5
    assert burst.selection_method == "quality"
```

**Step 2: Write Burst implementation**

```python
# lumina/models/burst.py
"""Burst model - groups of rapidly captured images."""

import uuid as uuid_module
from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field, Column
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID


class Burst(SQLModel, table=True):
    """Burst sequence of images."""

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
```

**Step 3: Write tests for Duplicate**

```python
# tests/models/test_duplicate.py
"""Tests for DuplicateGroup and DuplicateMember models."""

import uuid
from lumina.models.duplicate import DuplicateGroup, DuplicateMember, SimilarityType


def test_similarity_type_enum():
    """SimilarityType should distinguish exact vs perceptual."""
    assert SimilarityType.EXACT.value == "exact"
    assert SimilarityType.PERCEPTUAL.value == "perceptual"


def test_duplicate_group_creation():
    """DuplicateGroup should track primary image."""
    group = DuplicateGroup(
        catalog_id=uuid.uuid4(),
        primary_image_id="img-001",
        similarity_type=SimilarityType.PERCEPTUAL,
        confidence=95,
    )
    assert group.reviewed is False
    assert group.confidence == 95
```

**Step 4: Write Duplicate implementation**

```python
# lumina/models/duplicate.py
"""Duplicate detection models."""

import uuid as uuid_module
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import SQLModel, Field, Column
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID


class SimilarityType(str, Enum):
    """Type of duplicate match."""

    EXACT = "exact"
    PERCEPTUAL = "perceptual"


class DuplicateGroup(SQLModel, table=True):
    """Group of duplicate images."""

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
    """Member of a duplicate group."""

    __tablename__ = "duplicate_members"

    group_id: int = Field(foreign_key="duplicate_groups.id", primary_key=True)
    image_id: str = Field(foreign_key="images.id", primary_key=True)
    similarity_score: int  # 0-100
```

**Step 5: Write tests for Tag**

```python
# tests/models/test_tag.py
"""Tests for Tag and ImageTag models."""

import uuid
from lumina.models.tag import Tag, ImageTag, TagSource


def test_tag_source_enum():
    """TagSource should track origin of tags."""
    assert TagSource.MANUAL.value == "manual"
    assert TagSource.OPENCLIP.value == "openclip"
    assert TagSource.OLLAMA.value == "ollama"


def test_tag_creation():
    """Tag should have name and optional category."""
    tag = Tag(
        catalog_id=uuid.uuid4(),
        name="sunset",
        category="scene",
    )
    assert tag.name == "sunset"
```

**Step 6: Write Tag implementation**

```python
# lumina/models/tag.py
"""Tag models for image categorization."""

import uuid as uuid_module
from datetime import datetime
from enum import Enum
from typing import List, Optional

from sqlmodel import SQLModel, Field, Column
from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID


class TagSource(str, Enum):
    """Source of tag assignment."""

    MANUAL = "manual"
    OPENCLIP = "openclip"
    OLLAMA = "ollama"
    COMBINED = "combined"


class Tag(SQLModel, table=True):
    """Tag for categorizing images."""

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
    parent_id: Optional[int] = Field(
        default=None,
        foreign_key="tags.id",
    )
    synonyms: List[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text)),
    )
    description: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)


class ImageTag(SQLModel, table=True):
    """Many-to-many: Image <-> Tag with confidence."""

    __tablename__ = "image_tags"

    image_id: str = Field(foreign_key="images.id", primary_key=True)
    tag_id: int = Field(foreign_key="tags.id", primary_key=True)

    confidence: float = 1.0
    source: TagSource = TagSource.MANUAL

    openclip_confidence: Optional[float] = None
    ollama_confidence: Optional[float] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Step 7: Run all model tests**

Run: `pytest tests/models/ -v`
Expected: All PASS

**Step 8: Commit**

```bash
git add lumina/models/*.py tests/models/*.py
git commit -m "feat: add Burst, Duplicate, and Tag SQLModels"
```

---

## Phase 2: Generic Job Framework

### Task 2.1: Create Job Framework Core

**Files:**
- Create: `lumina/jobs/framework.py`
- Test: `tests/jobs/test_framework.py`

**Step 1: Write the failing test**

```python
# tests/jobs/test_framework.py
"""Tests for generic job framework."""

from typing import List
from lumina.jobs.framework import ParallelJob, JobRegistry


def test_parallel_job_definition():
    """ParallelJob should capture job configuration."""

    def discover(catalog_id: str) -> List[str]:
        return ["item1", "item2"]

    def process(item: str) -> dict:
        return {"item": item, "success": True}

    job = ParallelJob(
        name="test_job",
        discover=discover,
        process=process,
        batch_size=100,
    )

    assert job.name == "test_job"
    assert job.batch_size == 100


def test_job_registry():
    """JobRegistry should store and retrieve jobs."""
    registry = JobRegistry()

    job = ParallelJob(
        name="my_job",
        discover=lambda cid: [],
        process=lambda x: {},
    )

    registry.register(job)
    assert registry.get("my_job") == job
    assert "my_job" in registry.list_jobs()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/jobs/test_framework.py -v`
Expected: FAIL with import error

**Step 3: Write minimal implementation**

```python
# lumina/jobs/framework.py
"""Generic parallel job framework.

This module provides a declarative way to define parallel jobs.
Each job specifies:
- discover: How to find work items
- process: How to process a single item
- finalize: (optional) How to aggregate results

The framework handles batching, parallelization, progress tracking,
and error recovery automatically.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

T = TypeVar("T")  # Work item type
R = TypeVar("R")  # Result type


@dataclass
class ParallelJob(Generic[T]):
    """Definition of a parallel job.

    Args:
        name: Unique job identifier (e.g., "scan", "detect_duplicates")
        discover: Function(catalog_id) -> List[work_items]
        process: Function(item, **kwargs) -> result_dict
        finalize: Optional Function(results, catalog_id) -> final_result
        batch_size: Items per batch (default 1000)
        max_workers: Max parallel workers (default 4)
    """

    name: str
    discover: Callable[[str], List[T]]
    process: Callable[..., Dict[str, Any]]
    finalize: Optional[Callable[..., Dict[str, Any]]] = None
    batch_size: int = 1000
    max_workers: int = 4

    # Optional configuration
    retry_on_failure: bool = True
    max_retries: int = 3
    timeout_seconds: Optional[int] = None


class JobRegistry:
    """Registry of available parallel jobs."""

    def __init__(self) -> None:
        self._jobs: Dict[str, ParallelJob] = {}

    def register(self, job: ParallelJob) -> None:
        """Register a job definition."""
        self._jobs[job.name] = job

    def get(self, name: str) -> Optional[ParallelJob]:
        """Get a job by name."""
        return self._jobs.get(name)

    def list_jobs(self) -> List[str]:
        """List all registered job names."""
        return list(self._jobs.keys())


# Global registry
REGISTRY = JobRegistry()


def register_job(job: ParallelJob) -> ParallelJob:
    """Decorator/function to register a job globally."""
    REGISTRY.register(job)
    return job
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/jobs/test_framework.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lumina/jobs/framework.py tests/jobs/test_framework.py
git commit -m "feat: add ParallelJob framework core"
```

---

### Task 2.2: Create Job Executor

**Files:**
- Modify: `lumina/jobs/framework.py`
- Test: `tests/jobs/test_executor.py`

**Step 1: Write the failing test**

```python
# tests/jobs/test_executor.py
"""Tests for JobExecutor."""

import pytest
from unittest.mock import MagicMock, patch
from lumina.jobs.framework import ParallelJob, JobExecutor


def test_executor_runs_job():
    """Executor should run discover -> process -> finalize."""
    processed_items = []

    def discover(catalog_id: str) -> list:
        return ["a", "b", "c"]

    def process(item: str, **kwargs) -> dict:
        processed_items.append(item)
        return {"item": item, "ok": True}

    def finalize(results: list, catalog_id: str) -> dict:
        return {"total": len(results)}

    job = ParallelJob(
        name="test",
        discover=discover,
        process=process,
        finalize=finalize,
        batch_size=2,
        max_workers=2,
    )

    # Mock the database operations
    with patch("lumina.jobs.framework.get_db_session"):
        executor = JobExecutor(job)
        result = executor.run(
            job_id="job-1",
            catalog_id="cat-1",
        )

    assert set(processed_items) == {"a", "b", "c"}
    assert result["total"] == 3


def test_executor_handles_process_error():
    """Executor should track errors per item."""

    def discover(catalog_id: str) -> list:
        return ["good", "bad", "good2"]

    def process(item: str, **kwargs) -> dict:
        if item == "bad":
            raise ValueError("Item failed")
        return {"item": item}

    job = ParallelJob(
        name="test_errors",
        discover=discover,
        process=process,
        batch_size=10,
    )

    with patch("lumina.jobs.framework.get_db_session"):
        executor = JobExecutor(job)
        result = executor.run(job_id="job-2", catalog_id="cat-1")

    assert result["success_count"] == 2
    assert result["error_count"] == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/jobs/test_executor.py -v`
Expected: FAIL with "cannot import name 'JobExecutor'"

**Step 3: Write JobExecutor implementation**

Add to `lumina/jobs/framework.py`:

```python
# Add these imports at top
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class JobExecutor:
    """Executes a ParallelJob with batching and progress tracking.

    Handles:
    - Discovering work items
    - Creating batches
    - Parallel processing via ThreadPoolExecutor
    - Progress updates
    - Error tracking and recovery
    - Finalization
    """

    def __init__(self, job: ParallelJob):
        self.job = job

    def run(
        self,
        job_id: str,
        catalog_id: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Execute the job.

        Args:
            job_id: Unique job identifier for tracking
            catalog_id: Catalog to operate on
            **kwargs: Additional arguments passed to process()

        Returns:
            Final result dictionary
        """
        logger.info(f"[{job_id}] Starting job: {self.job.name}")

        # Phase 1: Discovery
        logger.info(f"[{job_id}] Discovering work items...")
        work_items = self.job.discover(catalog_id)
        total_items = len(work_items)
        logger.info(f"[{job_id}] Found {total_items} items to process")

        if total_items == 0:
            return self._empty_result()

        # Phase 2: Create batches
        batches = self._create_batches(work_items)
        logger.info(f"[{job_id}] Created {len(batches)} batches")

        # Phase 3: Process in parallel
        all_results = []
        success_count = 0
        error_count = 0
        errors = []

        with ThreadPoolExecutor(max_workers=self.job.max_workers) as executor:
            futures = {
                executor.submit(
                    self._process_batch,
                    batch,
                    catalog_id,
                    kwargs,
                ): i
                for i, batch in enumerate(batches)
            }

            for future in as_completed(futures):
                batch_num = futures[future]
                try:
                    batch_result = future.result()
                    all_results.extend(batch_result["results"])
                    success_count += batch_result["success_count"]
                    error_count += batch_result["error_count"]
                    errors.extend(batch_result.get("errors", []))

                    logger.debug(
                        f"[{job_id}] Batch {batch_num + 1}/{len(batches)} complete"
                    )
                except Exception as e:
                    logger.error(f"[{job_id}] Batch {batch_num} failed: {e}")
                    error_count += len(batches[batch_num])

        # Phase 4: Finalize
        if self.job.finalize:
            logger.info(f"[{job_id}] Running finalizer...")
            final_result = self.job.finalize(all_results, catalog_id)
        else:
            final_result = {}

        final_result.update({
            "success_count": success_count,
            "error_count": error_count,
            "total_items": total_items,
            "errors": errors[:100],  # Limit stored errors
        })

        logger.info(
            f"[{job_id}] Job complete: {success_count} success, {error_count} errors"
        )

        return final_result

    def _create_batches(self, items: List[T]) -> List[List[T]]:
        """Split items into batches."""
        batches = []
        for i in range(0, len(items), self.job.batch_size):
            batches.append(items[i : i + self.job.batch_size])
        return batches

    def _process_batch(
        self,
        batch: List[T],
        catalog_id: str,
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Process a single batch of items."""
        results = []
        success_count = 0
        error_count = 0
        errors = []

        for item in batch:
            try:
                result = self.job.process(item, catalog_id=catalog_id, **kwargs)
                results.append(result)
                success_count += 1
            except Exception as e:
                error_count += 1
                errors.append({
                    "item": str(item),
                    "error": str(e),
                })
                logger.warning(f"Error processing {item}: {e}")

        return {
            "results": results,
            "success_count": success_count,
            "error_count": error_count,
            "errors": errors,
        }

    def _empty_result(self) -> Dict[str, Any]:
        """Return result for empty job."""
        return {
            "success_count": 0,
            "error_count": 0,
            "total_items": 0,
            "errors": [],
        }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/jobs/test_executor.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lumina/jobs/framework.py tests/jobs/test_executor.py
git commit -m "feat: add JobExecutor for parallel job execution"
```

---

### Task 2.3: Add Database Integration to Executor

**Files:**
- Modify: `lumina/jobs/framework.py`
- Test: `tests/jobs/test_executor_db.py`

**Step 1: Write integration test**

```python
# tests/jobs/test_executor_db.py
"""Integration tests for JobExecutor with database."""

import pytest
from lumina.jobs.framework import ParallelJob, JobExecutor


@pytest.mark.integration
def test_executor_tracks_progress_in_db(db_session):
    """Executor should create JobBatch records."""
    # This test requires actual database
    pass  # Will implement when wiring up
```

**Step 2: Enhance JobExecutor with BatchManager integration**

Add to `lumina/jobs/framework.py`:

```python
class JobExecutorWithDB(JobExecutor):
    """JobExecutor with database-backed batch tracking.

    Extends JobExecutor to:
    - Create JobBatch records for restartability
    - Track progress in database
    - Support cancellation
    - Publish progress events
    """

    def __init__(self, job: ParallelJob, db_session_factory: Callable):
        super().__init__(job)
        self.db_session_factory = db_session_factory

    def run(
        self,
        job_id: str,
        catalog_id: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Execute with database tracking."""
        # For now, delegate to parent
        # Full implementation will use BatchManager pattern
        return super().run(job_id, catalog_id, **kwargs)
```

**Step 3: Commit**

```bash
git add lumina/jobs/framework.py tests/jobs/test_executor_db.py
git commit -m "feat: add JobExecutorWithDB skeleton for batch tracking"
```

---

## Phase 3: Pure Analysis Functions

### Task 3.1: Extract Pure Hash Functions

**Files:**
- Create: `lumina/analysis/hashing.py`
- Test: `tests/analysis/test_hashing_pure.py`

**Step 1: Write tests for pure functions**

```python
# tests/analysis/test_hashing_pure.py
"""Tests for pure hashing functions."""

from pathlib import Path
from lumina.analysis.hashing import (
    compute_dhash,
    compute_ahash,
    compute_whash,
    compute_all_hashes,
    hamming_distance,
)


def test_hamming_distance_identical():
    """Identical hashes should have distance 0."""
    h1 = "0000000000000000"
    h2 = "0000000000000000"
    assert hamming_distance(h1, h2) == 0


def test_hamming_distance_one_bit():
    """One bit difference should give distance 1."""
    h1 = "0000000000000000"
    h2 = "0000000000000001"
    assert hamming_distance(h1, h2) == 1


def test_compute_all_hashes(tmp_path, sample_image):
    """Should compute all three hash types."""
    hashes = compute_all_hashes(sample_image)
    assert "dhash" in hashes
    assert "ahash" in hashes
    assert "whash" in hashes
    assert all(len(h) == 16 for h in hashes.values())
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/analysis/test_hashing_pure.py -v`
Expected: FAIL with import error

**Step 3: Extract pure functions from perceptual_hash.py**

```python
# lumina/analysis/hashing.py
"""Pure functions for perceptual hashing.

These functions compute perceptual hashes for images without any
orchestration, progress tracking, or database access. They are
designed to be called by the job framework.

Hash types:
- dHash (difference hash): Gradient-based, good for crops/resizes
- aHash (average hash): Mean-based, simple but effective
- wHash (wavelet hash): DWT-based, most robust to transformations
"""

from pathlib import Path
from typing import Dict, Optional

from PIL import Image
import pywt
import numpy as np


def hamming_distance(hash1: str, hash2: str) -> int:
    """Compute Hamming distance between two hex hashes.

    Args:
        hash1: First hash as hex string
        hash2: Second hash as hex string

    Returns:
        Number of differing bits
    """
    if len(hash1) != len(hash2):
        raise ValueError(f"Hash length mismatch: {len(hash1)} vs {len(hash2)}")

    # Convert hex to int and XOR
    diff = int(hash1, 16) ^ int(hash2, 16)
    return bin(diff).count("1")


def compute_dhash(image_path: Path, hash_size: int = 8) -> str:
    """Compute difference hash (gradient-based).

    Args:
        image_path: Path to image file
        hash_size: Size of hash (default 8 = 64-bit hash)

    Returns:
        Hash as hex string
    """
    with Image.open(image_path) as img:
        # Convert to grayscale and resize
        img = img.convert("L")
        img = img.resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)

        pixels = list(img.getdata())

        # Compute differences
        bits = []
        for row in range(hash_size):
            for col in range(hash_size):
                left = pixels[row * (hash_size + 1) + col]
                right = pixels[row * (hash_size + 1) + col + 1]
                bits.append(1 if left > right else 0)

        # Convert to hex
        hash_int = int("".join(str(b) for b in bits), 2)
        return format(hash_int, f"0{hash_size * hash_size // 4}x")


def compute_ahash(image_path: Path, hash_size: int = 8) -> str:
    """Compute average hash (mean-based).

    Args:
        image_path: Path to image file
        hash_size: Size of hash grid

    Returns:
        Hash as hex string
    """
    with Image.open(image_path) as img:
        img = img.convert("L")
        img = img.resize((hash_size, hash_size), Image.Resampling.LANCZOS)

        pixels = list(img.getdata())
        avg = sum(pixels) / len(pixels)

        bits = [1 if p > avg else 0 for p in pixels]
        hash_int = int("".join(str(b) for b in bits), 2)
        return format(hash_int, f"0{hash_size * hash_size // 4}x")


def compute_whash(image_path: Path, hash_size: int = 8) -> str:
    """Compute wavelet hash (DWT-based).

    Most robust to transformations like rotation, scaling, compression.

    Args:
        image_path: Path to image file
        hash_size: Size of hash grid

    Returns:
        Hash as hex string
    """
    with Image.open(image_path) as img:
        img = img.convert("L")
        # Resize to power of 2 for DWT
        img = img.resize((hash_size * 4, hash_size * 4), Image.Resampling.LANCZOS)

        pixels = np.array(img, dtype=np.float64)

        # Apply 2D DWT
        coeffs = pywt.dwt2(pixels, "haar")
        cA, (cH, cV, cD) = coeffs

        # Resize approximation coefficients
        cA_resized = Image.fromarray(cA).resize(
            (hash_size, hash_size), Image.Resampling.LANCZOS
        )
        cA_array = np.array(cA_resized)

        # Threshold by median
        median = np.median(cA_array)
        bits = (cA_array > median).flatten().astype(int)

        hash_int = int("".join(str(b) for b in bits), 2)
        return format(hash_int, f"0{hash_size * hash_size // 4}x")


def compute_all_hashes(
    image_path: Path,
    hash_size: int = 8,
) -> Dict[str, str]:
    """Compute all three hash types for an image.

    Args:
        image_path: Path to image file
        hash_size: Size of hash grid

    Returns:
        Dict with keys: dhash, ahash, whash
    """
    return {
        "dhash": compute_dhash(image_path, hash_size),
        "ahash": compute_ahash(image_path, hash_size),
        "whash": compute_whash(image_path, hash_size),
    }


def similarity_score(hash1: str, hash2: str, hash_bits: int = 64) -> int:
    """Compute similarity percentage between two hashes.

    Args:
        hash1: First hash as hex string
        hash2: Second hash as hex string
        hash_bits: Total bits in hash (default 64 for 8x8)

    Returns:
        Similarity as percentage 0-100
    """
    distance = hamming_distance(hash1, hash2)
    return int(100 * (1 - distance / hash_bits))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/analysis/test_hashing_pure.py -v`
Expected: PASS (after adding sample_image fixture)

**Step 5: Commit**

```bash
git add lumina/analysis/hashing.py tests/analysis/test_hashing_pure.py
git commit -m "feat: extract pure hashing functions"
```

---

### Task 3.2: Extract Pure Duplicate Grouping

**Files:**
- Create: `lumina/analysis/duplicates.py`
- Test: `tests/analysis/test_duplicates_pure.py`

**Step 1: Write tests**

```python
# tests/analysis/test_duplicates_pure.py
"""Tests for pure duplicate detection functions."""

from lumina.analysis.duplicates import (
    group_by_exact_match,
    group_by_similarity,
    find_similar_hashes,
)


def test_group_by_exact_match():
    """Should group images with identical checksums."""
    images = [
        {"id": "1", "checksum": "abc"},
        {"id": "2", "checksum": "def"},
        {"id": "3", "checksum": "abc"},
        {"id": "4", "checksum": "def"},
        {"id": "5", "checksum": "ghi"},
    ]

    groups = group_by_exact_match(images)

    assert len(groups) == 2  # Two groups with duplicates
    group_ids = [sorted(g["image_ids"]) for g in groups]
    assert ["1", "3"] in group_ids
    assert ["2", "4"] in group_ids


def test_find_similar_hashes():
    """Should find hashes within threshold."""
    hashes = {
        "img1": "0000000000000000",
        "img2": "0000000000000001",  # 1 bit diff
        "img3": "ffffffffffffffff",  # Very different
        "img4": "0000000000000003",  # 2 bits diff from img1
    }

    similar = find_similar_hashes(hashes, threshold=5)

    # img1, img2, img4 should be grouped (within threshold)
    # img3 should be separate
    assert len(similar) >= 1
```

**Step 2: Write implementation**

```python
# lumina/analysis/duplicates.py
"""Pure functions for duplicate detection.

These functions identify duplicate and similar images based on
checksums and perceptual hashes. They handle grouping logic
without database access or progress tracking.
"""

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from .hashing import hamming_distance


def group_by_exact_match(
    images: List[Dict[str, Any]],
    checksum_key: str = "checksum",
) -> List[Dict[str, Any]]:
    """Group images by exact checksum match.

    Args:
        images: List of image dicts with checksum field
        checksum_key: Key for checksum in image dict

    Returns:
        List of group dicts with image_ids and similarity_type
    """
    by_checksum: Dict[str, List[str]] = defaultdict(list)

    for img in images:
        checksum = img.get(checksum_key)
        if checksum:
            by_checksum[checksum].append(img["id"])

    groups = []
    for checksum, ids in by_checksum.items():
        if len(ids) > 1:
            groups.append({
                "image_ids": ids,
                "similarity_type": "exact",
                "confidence": 100,
            })

    return groups


def find_similar_hashes(
    hashes: Dict[str, str],
    threshold: int = 5,
) -> List[Set[str]]:
    """Find groups of similar hashes using union-find.

    Args:
        hashes: Dict mapping image_id -> hash string
        threshold: Maximum Hamming distance to consider similar

    Returns:
        List of sets, each containing similar image IDs
    """
    # Union-find for efficient grouping
    parent: Dict[str, str] = {id: id for id in hashes}

    def find(x: str) -> str:
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x: str, y: str) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    # Compare all pairs
    ids = list(hashes.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            id1, id2 = ids[i], ids[j]
            distance = hamming_distance(hashes[id1], hashes[id2])
            if distance <= threshold:
                union(id1, id2)

    # Collect groups
    groups: Dict[str, Set[str]] = defaultdict(set)
    for id in ids:
        root = find(id)
        groups[root].add(id)

    # Return only groups with multiple members
    return [g for g in groups.values() if len(g) > 1]


def group_by_similarity(
    images: List[Dict[str, Any]],
    hash_key: str = "dhash",
    threshold: int = 5,
) -> List[Dict[str, Any]]:
    """Group images by perceptual hash similarity.

    Args:
        images: List of image dicts with hash field
        hash_key: Key for hash in image dict (dhash, ahash, whash)
        threshold: Maximum Hamming distance

    Returns:
        List of group dicts with image_ids, similarity_type, confidence
    """
    # Build hash lookup
    hashes = {}
    for img in images:
        hash_val = img.get(hash_key)
        if hash_val:
            hashes[img["id"]] = hash_val

    if not hashes:
        return []

    # Find similar groups
    similar_sets = find_similar_hashes(hashes, threshold)

    # Convert to output format
    groups = []
    for id_set in similar_sets:
        # Calculate average similarity within group
        ids = list(id_set)
        total_dist = 0
        comparisons = 0
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                total_dist += hamming_distance(hashes[ids[i]], hashes[ids[j]])
                comparisons += 1

        avg_dist = total_dist / comparisons if comparisons else 0
        # Convert distance to confidence (lower distance = higher confidence)
        # threshold of 5 on 64-bit hash means max distance is ~8% of bits
        confidence = int(100 * (1 - avg_dist / 64))

        groups.append({
            "image_ids": ids,
            "similarity_type": "perceptual",
            "confidence": max(0, min(100, confidence)),
        })

    return groups


def select_primary_image(
    images: List[Dict[str, Any]],
    quality_key: str = "quality_score",
) -> str:
    """Select the best image from a group as primary.

    Selection criteria (in order):
    1. Highest quality score
    2. Largest file size
    3. First by ID (deterministic)

    Args:
        images: List of image dicts
        quality_key: Key for quality score

    Returns:
        ID of the primary image
    """
    if not images:
        raise ValueError("Cannot select from empty list")

    def sort_key(img: Dict[str, Any]) -> Tuple:
        return (
            img.get(quality_key) or 0,
            img.get("size_bytes") or 0,
            img.get("id", ""),
        )

    best = max(images, key=sort_key)
    return best["id"]
```

**Step 3: Run tests**

Run: `pytest tests/analysis/test_duplicates_pure.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add lumina/analysis/duplicates.py tests/analysis/test_duplicates_pure.py
git commit -m "feat: extract pure duplicate detection functions"
```

---

### Task 3.3: Extract Pure Burst Detection

**Files:**
- Create: `lumina/analysis/bursts.py`
- Test: `tests/analysis/test_bursts_pure.py`

**Step 1: Write tests**

```python
# tests/analysis/test_bursts_pure.py
"""Tests for pure burst detection functions."""

from datetime import datetime, timedelta
from lumina.analysis.bursts import detect_bursts, select_best_in_burst


def test_detect_bursts_basic():
    """Should detect images taken in rapid succession."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)

    images = [
        {"id": "1", "timestamp": base_time, "camera": "Canon"},
        {"id": "2", "timestamp": base_time + timedelta(seconds=0.5), "camera": "Canon"},
        {"id": "3", "timestamp": base_time + timedelta(seconds=1.0), "camera": "Canon"},
        {"id": "4", "timestamp": base_time + timedelta(hours=1), "camera": "Canon"},
    ]

    bursts = detect_bursts(images, gap_threshold=2.0, min_size=3)

    assert len(bursts) == 1
    assert set(bursts[0]["image_ids"]) == {"1", "2", "3"}


def test_detect_bursts_different_cameras():
    """Should not group images from different cameras."""
    base_time = datetime(2024, 1, 1, 12, 0, 0)

    images = [
        {"id": "1", "timestamp": base_time, "camera": "Canon"},
        {"id": "2", "timestamp": base_time + timedelta(seconds=0.5), "camera": "Nikon"},
        {"id": "3", "timestamp": base_time + timedelta(seconds=1.0), "camera": "Canon"},
    ]

    bursts = detect_bursts(images, gap_threshold=2.0, min_size=2)

    # Should not form a burst across different cameras
    assert len(bursts) == 0


def test_select_best_in_burst():
    """Should select highest quality image."""
    images = [
        {"id": "1", "quality_score": 70},
        {"id": "2", "quality_score": 95},
        {"id": "3", "quality_score": 85},
    ]

    best = select_best_in_burst(images)
    assert best == "2"
```

**Step 2: Write implementation**

```python
# lumina/analysis/bursts.py
"""Pure functions for burst sequence detection.

Detects groups of images taken in rapid succession (bursts) based on
timestamps and camera metadata. Pure algorithmic approach - no ML.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def detect_bursts(
    images: List[Dict[str, Any]],
    gap_threshold: float = 1.0,
    min_size: int = 3,
    min_duration: float = 0.5,
) -> List[Dict[str, Any]]:
    """Detect burst sequences in a list of images.

    A burst is defined as:
    - Images from the same camera
    - Taken within gap_threshold seconds of each other
    - At least min_size images
    - Total duration >= min_duration

    Args:
        images: List of image dicts with timestamp, camera fields
        gap_threshold: Maximum seconds between consecutive images
        min_size: Minimum images to form a burst
        min_duration: Minimum total duration in seconds

    Returns:
        List of burst dicts with image_ids, start_time, end_time, duration
    """
    if len(images) < min_size:
        return []

    # Group by camera
    by_camera: Dict[str, List[Dict]] = {}
    for img in images:
        camera = img.get("camera") or "unknown"
        if camera not in by_camera:
            by_camera[camera] = []
        by_camera[camera].append(img)

    all_bursts = []

    for camera, camera_images in by_camera.items():
        # Sort by timestamp
        sorted_imgs = sorted(
            camera_images,
            key=lambda x: x.get("timestamp") or datetime.min,
        )

        # Find sequences
        bursts = _find_sequences(sorted_imgs, gap_threshold, min_size, min_duration)
        all_bursts.extend(bursts)

    return all_bursts


def _find_sequences(
    sorted_images: List[Dict[str, Any]],
    gap_threshold: float,
    min_size: int,
    min_duration: float,
) -> List[Dict[str, Any]]:
    """Find burst sequences in time-sorted images."""
    if len(sorted_images) < min_size:
        return []

    bursts = []
    current: List[Dict] = [sorted_images[0]]

    for i in range(1, len(sorted_images)):
        curr_img = sorted_images[i]
        prev_img = sorted_images[i - 1]

        curr_ts = curr_img.get("timestamp")
        prev_ts = prev_img.get("timestamp")

        if curr_ts and prev_ts:
            gap = (curr_ts - prev_ts).total_seconds()
        else:
            gap = float("inf")

        if gap <= gap_threshold:
            current.append(curr_img)
        else:
            # End of sequence - check if it's a valid burst
            if len(current) >= min_size:
                burst = _make_burst(current, min_duration)
                if burst:
                    bursts.append(burst)
            current = [curr_img]

    # Check final sequence
    if len(current) >= min_size:
        burst = _make_burst(current, min_duration)
        if burst:
            bursts.append(burst)

    return bursts


def _make_burst(
    images: List[Dict[str, Any]],
    min_duration: float,
) -> Optional[Dict[str, Any]]:
    """Create a burst dict if it meets duration requirement."""
    if len(images) < 2:
        return None

    timestamps = [img.get("timestamp") for img in images if img.get("timestamp")]
    if len(timestamps) < 2:
        return None

    start = min(timestamps)
    end = max(timestamps)
    duration = (end - start).total_seconds()

    if duration < min_duration:
        return None

    return {
        "image_ids": [img["id"] for img in images],
        "start_time": start,
        "end_time": end,
        "duration_seconds": duration,
        "camera": images[0].get("camera"),
    }


def select_best_in_burst(
    images: List[Dict[str, Any]],
    method: str = "quality",
) -> str:
    """Select the best image from a burst.

    Args:
        images: List of image dicts
        method: Selection method (quality, first, middle)

    Returns:
        ID of the best image
    """
    if not images:
        raise ValueError("Cannot select from empty list")

    if method == "first":
        return images[0]["id"]
    elif method == "middle":
        return images[len(images) // 2]["id"]
    else:  # quality
        best = max(images, key=lambda x: x.get("quality_score") or 0)
        return best["id"]
```

**Step 3: Run tests**

Run: `pytest tests/analysis/test_bursts_pure.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add lumina/analysis/bursts.py tests/analysis/test_bursts_pure.py
git commit -m "feat: extract pure burst detection functions"
```

---

## Phase 4: Job Definitions

### Task 4.1: Define Scan Job

**Files:**
- Create: `lumina/jobs/definitions/__init__.py`
- Create: `lumina/jobs/definitions/scan.py`
- Test: `tests/jobs/definitions/test_scan.py`

**Step 1: Write test**

```python
# tests/jobs/definitions/test_scan.py
"""Tests for scan job definition."""

from lumina.jobs.definitions.scan import scan_job
from lumina.jobs.framework import REGISTRY


def test_scan_job_registered():
    """Scan job should be in global registry."""
    assert REGISTRY.get("scan") is not None
    assert scan_job.name == "scan"


def test_scan_job_has_required_functions():
    """Scan job should have discover and process."""
    assert callable(scan_job.discover)
    assert callable(scan_job.process)
```

**Step 2: Write implementation**

```python
# lumina/jobs/definitions/__init__.py
"""Job definitions - import all to register."""

from . import scan
from . import duplicates
from . import bursts

__all__ = ["scan", "duplicates", "bursts"]
```

```python
# lumina/jobs/definitions/scan.py
"""Scan job definition.

Discovers and processes media files in source directories.
"""

from pathlib import Path
from typing import Any, Dict, List

from ..framework import ParallelJob, register_job


def discover_files(catalog_id: str) -> List[str]:
    """Discover files to scan in catalog source directories.

    Args:
        catalog_id: The catalog UUID

    Returns:
        List of file paths to process
    """
    # Import here to avoid circular deps
    from ...db import get_catalog_source_dirs

    source_dirs = get_catalog_source_dirs(catalog_id)
    files = []

    MEDIA_EXTENSIONS = {
        ".jpg", ".jpeg", ".png", ".gif", ".heic", ".heif",
        ".raw", ".cr2", ".nef", ".arw", ".dng",
        ".mp4", ".mov", ".avi", ".mkv",
    }

    for dir_path in source_dirs:
        path = Path(dir_path)
        if path.exists():
            for file in path.rglob("*"):
                if file.is_file() and file.suffix.lower() in MEDIA_EXTENSIONS:
                    files.append(str(file))

    return files


def process_file(
    file_path: str,
    catalog_id: str,
    generate_thumbnail: bool = True,
    extract_metadata: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    """Process a single media file.

    Args:
        file_path: Path to the file
        catalog_id: The catalog UUID
        generate_thumbnail: Whether to generate thumbnail
        extract_metadata: Whether to extract EXIF metadata

    Returns:
        Processing result dict
    """
    from pathlib import Path
    import hashlib

    from ...analysis.metadata import extract_metadata as extract_meta
    from ...shared.thumbnail_utils import generate_thumbnail as gen_thumb

    path = Path(file_path)

    # Compute checksum
    with open(path, "rb") as f:
        checksum = hashlib.sha256(f.read()).hexdigest()

    result = {
        "path": file_path,
        "checksum": checksum,
        "size_bytes": path.stat().st_size,
    }

    # Extract metadata
    if extract_metadata:
        try:
            metadata = extract_meta(path)
            result["metadata"] = metadata
        except Exception as e:
            result["metadata_error"] = str(e)

    # Generate thumbnail
    if generate_thumbnail:
        try:
            thumb_path = gen_thumb(path, catalog_id)
            result["thumbnail_path"] = thumb_path
        except Exception as e:
            result["thumbnail_error"] = str(e)

    return result


def finalize_scan(
    results: List[Dict[str, Any]],
    catalog_id: str,
) -> Dict[str, Any]:
    """Finalize scan job - compute statistics.

    Args:
        results: All processing results
        catalog_id: The catalog UUID

    Returns:
        Summary statistics
    """
    total_size = sum(r.get("size_bytes", 0) for r in results)
    images = sum(1 for r in results if r.get("path", "").lower().endswith(
        (".jpg", ".jpeg", ".png", ".heic", ".raw", ".cr2", ".nef")
    ))
    videos = len(results) - images

    return {
        "total_files": len(results),
        "total_images": images,
        "total_videos": videos,
        "total_size_bytes": total_size,
    }


scan_job = register_job(ParallelJob(
    name="scan",
    discover=discover_files,
    process=process_file,
    finalize=finalize_scan,
    batch_size=500,
    max_workers=4,
))
```

**Step 3: Run tests**

Run: `pytest tests/jobs/definitions/test_scan.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add lumina/jobs/definitions/ tests/jobs/definitions/
git commit -m "feat: add scan job definition"
```

---

### Task 4.2: Define Duplicates Job

**Files:**
- Create: `lumina/jobs/definitions/duplicates.py`
- Test: `tests/jobs/definitions/test_duplicates.py`

**Step 1: Write test**

```python
# tests/jobs/definitions/test_duplicates.py
"""Tests for duplicates job definition."""

from lumina.jobs.definitions.duplicates import duplicates_job
from lumina.jobs.framework import REGISTRY


def test_duplicates_job_registered():
    """Duplicates job should be in global registry."""
    assert REGISTRY.get("detect_duplicates") is not None


def test_duplicates_job_configuration():
    """Duplicates job should have appropriate settings."""
    assert duplicates_job.batch_size == 1000
    assert duplicates_job.finalize is not None
```

**Step 2: Write implementation**

```python
# lumina/jobs/definitions/duplicates.py
"""Duplicate detection job definition.

Computes perceptual hashes and groups similar images.
"""

from typing import Any, Dict, List

from ..framework import ParallelJob, register_job


def discover_images_for_hashing(catalog_id: str) -> List[str]:
    """Find images that need hash computation.

    Args:
        catalog_id: The catalog UUID

    Returns:
        List of image IDs without hashes
    """
    from ...db import get_images_without_hashes
    return get_images_without_hashes(catalog_id)


def compute_image_hashes(
    image_id: str,
    catalog_id: str,
    **kwargs,
) -> Dict[str, Any]:
    """Compute perceptual hashes for an image.

    Args:
        image_id: The image ID
        catalog_id: The catalog UUID

    Returns:
        Hash computation result
    """
    from ...db import get_image_path
    from ...analysis.hashing import compute_all_hashes

    path = get_image_path(catalog_id, image_id)

    try:
        hashes = compute_all_hashes(path)
        return {
            "image_id": image_id,
            "hashes": hashes,
            "success": True,
        }
    except Exception as e:
        return {
            "image_id": image_id,
            "error": str(e),
            "success": False,
        }


def finalize_duplicates(
    results: List[Dict[str, Any]],
    catalog_id: str,
) -> Dict[str, Any]:
    """Group images by similarity after hash computation.

    Args:
        results: Hash computation results
        catalog_id: The catalog UUID

    Returns:
        Grouping results
    """
    from ...analysis.duplicates import (
        group_by_exact_match,
        group_by_similarity,
    )
    from ...db import get_images_with_hashes, save_duplicate_groups

    # Get all images with hashes
    images = get_images_with_hashes(catalog_id)

    # Find exact duplicates
    exact_groups = group_by_exact_match(images)

    # Find perceptual duplicates (using dhash by default)
    perceptual_groups = group_by_similarity(images, hash_key="dhash", threshold=5)

    # Save to database
    all_groups = exact_groups + perceptual_groups
    save_duplicate_groups(catalog_id, all_groups)

    return {
        "exact_groups": len(exact_groups),
        "perceptual_groups": len(perceptual_groups),
        "total_duplicates": sum(len(g["image_ids"]) for g in all_groups),
    }


duplicates_job = register_job(ParallelJob(
    name="detect_duplicates",
    discover=discover_images_for_hashing,
    process=compute_image_hashes,
    finalize=finalize_duplicates,
    batch_size=1000,
    max_workers=4,
))
```

**Step 3: Commit**

```bash
git add lumina/jobs/definitions/duplicates.py tests/jobs/definitions/test_duplicates.py
git commit -m "feat: add duplicates job definition"
```

---

### Task 4.3: Define Bursts Job

**Files:**
- Create: `lumina/jobs/definitions/bursts.py`
- Test: `tests/jobs/definitions/test_bursts.py`

**Step 1: Write implementation**

```python
# lumina/jobs/definitions/bursts.py
"""Burst detection job definition.

Detects sequences of rapidly captured images.
"""

from typing import Any, Dict, List

from ..framework import ParallelJob, register_job


def discover_images_for_bursts(catalog_id: str) -> List[Dict[str, Any]]:
    """Get all images with timestamps for burst detection.

    Returns images as dicts since burst detection needs multiple fields.
    """
    from ...db import get_images_with_timestamps
    return get_images_with_timestamps(catalog_id)


def detect_catalog_bursts(
    images: List[Dict[str, Any]],
    catalog_id: str,
    **kwargs,
) -> Dict[str, Any]:
    """Detect bursts in catalog images.

    Note: This is a single-pass algorithm, not per-item processing.
    The job framework calls this once with all images.
    """
    from ...analysis.bursts import detect_bursts, select_best_in_burst
    from ...db import save_burst_groups

    # Detect bursts
    bursts = detect_bursts(
        images,
        gap_threshold=kwargs.get("gap_threshold", 1.0),
        min_size=kwargs.get("min_size", 3),
    )

    # Select best image in each burst
    for burst in bursts:
        burst_images = [img for img in images if img["id"] in burst["image_ids"]]
        burst["best_image_id"] = select_best_in_burst(burst_images)

    # Save to database
    save_burst_groups(catalog_id, bursts)

    return {
        "bursts_detected": len(bursts),
        "images_in_bursts": sum(len(b["image_ids"]) for b in bursts),
    }


# Bursts job is single-pass, not parallel per-item
# Use batch_size = total to process all at once
bursts_job = register_job(ParallelJob(
    name="detect_bursts",
    discover=discover_images_for_bursts,
    process=detect_catalog_bursts,
    finalize=None,  # Processing function handles everything
    batch_size=100000,  # Large batch = single pass
    max_workers=1,  # Single worker for this algorithm
))
```

**Step 2: Commit**

```bash
git add lumina/jobs/definitions/bursts.py tests/jobs/definitions/test_bursts.py
git commit -m "feat: add bursts job definition"
```

---

## Phase 5: Repository Pattern

### Task 5.1: Create Base Repository

**Files:**
- Create: `lumina/db/repositories/__init__.py`
- Create: `lumina/db/repositories/base.py`
- Test: `tests/db/repositories/test_base.py`

**Step 1: Write implementation**

```python
# lumina/db/repositories/base.py
"""Base repository pattern for data access."""

from typing import Generic, List, Optional, Type, TypeVar
from sqlmodel import Session, SQLModel, select

T = TypeVar("T", bound=SQLModel)


class BaseRepository(Generic[T]):
    """Generic repository with CRUD operations."""

    def __init__(self, session: Session, model: Type[T]):
        self.session = session
        self.model = model

    def get(self, id: str) -> Optional[T]:
        """Get entity by ID."""
        return self.session.get(self.model, id)

    def list(self, limit: int = 100, offset: int = 0) -> List[T]:
        """List entities with pagination."""
        stmt = select(self.model).offset(offset).limit(limit)
        return list(self.session.exec(stmt).all())

    def add(self, entity: T) -> T:
        """Add new entity."""
        self.session.add(entity)
        self.session.flush()
        return entity

    def update(self, entity: T) -> T:
        """Update existing entity."""
        self.session.add(entity)
        self.session.flush()
        return entity

    def delete(self, entity: T) -> None:
        """Delete entity."""
        self.session.delete(entity)
        self.session.flush()

    def commit(self) -> None:
        """Commit transaction."""
        self.session.commit()

    def rollback(self) -> None:
        """Rollback transaction."""
        self.session.rollback()
```

**Step 2: Commit**

```bash
git add lumina/db/repositories/
git commit -m "feat: add base repository pattern"
```

---

### Task 5.2: Create Image Repository

**Files:**
- Create: `lumina/db/repositories/image.py`
- Test: `tests/db/repositories/test_image.py`

**Step 1: Write implementation**

```python
# lumina/db/repositories/image.py
"""Image repository for data access."""

import uuid
from typing import Dict, List, Optional, Any

from sqlmodel import Session, select, col

from .base import BaseRepository
from ...models.image import Image, ProcessingStatus


class ImageRepository(BaseRepository[Image]):
    """Repository for Image operations."""

    def __init__(self, session: Session):
        super().__init__(session, Image)

    def get_by_catalog(
        self,
        catalog_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
        status: Optional[ProcessingStatus] = None,
    ) -> List[Image]:
        """Get images in a catalog."""
        stmt = select(Image).where(Image.catalog_id == catalog_id)
        if status:
            stmt = stmt.where(Image.status == status)
        stmt = stmt.offset(offset).limit(limit)
        return list(self.session.exec(stmt).all())

    def get_without_hashes(self, catalog_id: uuid.UUID) -> List[str]:
        """Get image IDs that need hash computation."""
        stmt = (
            select(Image.id)
            .where(Image.catalog_id == catalog_id)
            .where(Image.dhash.is_(None))
        )
        return [row for row in self.session.exec(stmt).all()]

    def get_with_hashes(self, catalog_id: uuid.UUID) -> List[Dict[str, Any]]:
        """Get images with their hashes for duplicate detection."""
        stmt = (
            select(Image)
            .where(Image.catalog_id == catalog_id)
            .where(Image.dhash.isnot(None))
        )
        images = self.session.exec(stmt).all()
        return [
            {
                "id": img.id,
                "checksum": img.checksum,
                "dhash": img.dhash,
                "ahash": img.ahash,
                "whash": img.whash,
                "quality_score": img.quality_score,
                "size_bytes": img.size_bytes,
            }
            for img in images
        ]

    def get_with_timestamps(self, catalog_id: uuid.UUID) -> List[Dict[str, Any]]:
        """Get images with timestamps for burst detection."""
        stmt = select(Image).where(Image.catalog_id == catalog_id)
        images = self.session.exec(stmt).all()

        results = []
        for img in images:
            dates = img.dates or {}
            metadata = img.metadata_json or {}

            results.append({
                "id": img.id,
                "timestamp": dates.get("selected_date"),
                "camera": f"{metadata.get('camera_make', '')} {metadata.get('camera_model', '')}".strip() or None,
                "quality_score": img.quality_score,
            })
        return results

    def update_hashes(
        self,
        image_id: str,
        dhash: str,
        ahash: str,
        whash: str,
    ) -> None:
        """Update image hashes."""
        image = self.get(image_id)
        if image:
            image.dhash = dhash
            image.ahash = ahash
            image.whash = whash
            self.update(image)
```

**Step 2: Commit**

```bash
git add lumina/db/repositories/image.py tests/db/repositories/
git commit -m "feat: add ImageRepository"
```

---

## Phase 6: API Consolidation

### Task 6.1: Create Unified Images Router

**Files:**
- Create: `lumina/api/routers/images.py`
- Test: `tests/api/test_images_router.py`

**Step 1: Write implementation**

```python
# lumina/api/routers/images.py
"""Unified images API router.

Handles all image operations for the UI:
- Listing and filtering images
- Thumbnail serving
- Full image serving
- Metadata retrieval
- Rating and tagging
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlmodel import Session

from ...db import get_session
from ...db.repositories.image import ImageRepository
from ...models.image import Image, ImageRead, ProcessingStatus

router = APIRouter(prefix="/images", tags=["images"])


@router.get("", response_model=List[ImageRead])
def list_images(
    catalog_id: uuid.UUID,
    status: Optional[ProcessingStatus] = None,
    rating_gte: Optional[int] = Query(None, ge=0, le=5),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    """List images in a catalog with filtering."""
    repo = ImageRepository(session)
    return repo.get_by_catalog(
        catalog_id=catalog_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/{image_id}", response_model=ImageRead)
def get_image(
    image_id: str,
    session: Session = Depends(get_session),
):
    """Get a single image by ID."""
    repo = ImageRepository(session)
    image = repo.get(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    return image


@router.get("/{image_id}/thumbnail")
def get_thumbnail(
    image_id: str,
    size: str = Query("medium", regex="^(small|medium|large)$"),
    session: Session = Depends(get_session),
):
    """Get image thumbnail."""
    repo = ImageRepository(session)
    image = repo.get(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    if not image.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not available")

    return FileResponse(
        image.thumbnail_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{image_id}/full")
def get_full_image(
    image_id: str,
    session: Session = Depends(get_session),
):
    """Get full-size image."""
    repo = ImageRepository(session)
    image = repo.get(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    # Determine media type from extension
    path = image.source_path.lower()
    if path.endswith(".png"):
        media_type = "image/png"
    elif path.endswith((".jpg", ".jpeg")):
        media_type = "image/jpeg"
    elif path.endswith(".heic"):
        media_type = "image/heic"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        image.source_path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.patch("/{image_id}")
def update_image(
    image_id: str,
    rating: Optional[int] = Query(None, ge=0, le=5),
    session: Session = Depends(get_session),
):
    """Update image properties (rating, etc.)."""
    repo = ImageRepository(session)
    image = repo.get(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    if rating is not None:
        image.quality_score = rating * 20  # Convert 0-5 to 0-100

    repo.update(image)
    repo.commit()
    return {"status": "updated"}
```

**Step 2: Commit**

```bash
git add lumina/api/routers/images.py tests/api/test_images_router.py
git commit -m "feat: add unified images API router"
```

---

## Phase 7: Cleanup Legacy Code

### Task 7.1: Remove lumina/web/ Directory

**Step 1: Delete the directory**

```bash
rm -rf lumina/web/
```

**Step 2: Update imports that reference it**

Search for and remove any imports from `lumina.web`.

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove legacy lumina/web module"
```

---

### Task 7.2: Remove Old Parallel Job Files

**Step 1: Delete the files** (after jobs/definitions/ is working)

```bash
rm lumina/jobs/parallel_scan.py
rm lumina/jobs/parallel_duplicates.py
rm lumina/jobs/parallel_bursts.py
rm lumina/jobs/parallel_tagging.py
rm lumina/jobs/parallel_quality.py
rm lumina/jobs/parallel_thumbnails.py
```

**Step 2: Update coordinator.py to use new framework**

Keep the BatchManager but wire it to new JobExecutor.

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove legacy parallel job files"
```

---

### Task 7.3: Remove Old Model Files

**Step 1: Migrate catalog_db.py to use repositories**

Update imports and gradually replace direct database access.

**Step 2: Remove serializers.py**

SQLModel eliminates the need for manual serialization.

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove legacy serializers and CatalogDB"
```

---

## Phase 8: Integration and Testing

### Task 8.1: Update Test Fixtures

**Files:**
- Modify: `tests/conftest.py`

Add fixtures for new models and repositories.

### Task 8.2: Run Full Test Suite

```bash
pytest tests/ -v --tb=short
```

Ensure all tests pass with new architecture.

### Task 8.3: Performance Benchmarks

Compare job execution time before and after refactor.

---

## Summary

This plan transforms Lumina from ~34,000 LOC to ~4,500 LOC by:

1. **Unified Models** (Phase 1): SQLModel replaces separate Pydantic + SQLAlchemy definitions
2. **Generic Job Framework** (Phase 2): ParallelJob + JobExecutor replace 6 parallel_*.py files
3. **Pure Analysis Functions** (Phase 3): Extract algorithms from orchestration code
4. **Declarative Job Definitions** (Phase 4): ~30 lines per job instead of ~300
5. **Repository Pattern** (Phase 5): Clean data access layer
6. **Consolidated API** (Phase 6): Single unified API for UI
7. **Cleanup** (Phase 7): Remove legacy code
8. **Testing** (Phase 8): Ensure everything works

**Estimated commits:** ~25
**Estimated tasks:** 30-35

---

Plan complete and saved to `docs/plans/2026-02-03-v2-architecture.md`.

**Two execution options:**

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**
