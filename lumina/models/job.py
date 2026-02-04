"""Job and JobBatch models - tracks async processing jobs."""

import uuid as uuid_module
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel


class JobStatus(str, Enum):
    """Status for jobs."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BatchStatus(str, Enum):
    """Status for job batches."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(SQLModel, table=True):
    """Job database model - tracks async processing jobs."""

    __tablename__ = "jobs"

    id: str = Field(primary_key=True)
    catalog_id: Optional[uuid_module.UUID] = Field(default=None, nullable=True)
    job_type: str = Field(max_length=50)
    status: JobStatus = Field(default=JobStatus.PENDING)
    parameters: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, default={})
    )
    progress: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, default={})
    )
    result: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, default={})
    )
    error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class JobBatch(SQLModel, table=True):
    """JobBatch database model - tracks batches of work for a parent job."""

    __tablename__ = "job_batches"

    id: uuid_module.UUID = Field(
        default_factory=uuid_module.uuid4,
        primary_key=True,
    )
    parent_job_id: str = Field(foreign_key="jobs.id")
    catalog_id: uuid_module.UUID
    batch_number: int
    total_batches: int
    job_type: str = Field(max_length=50)
    status: BatchStatus = Field(default=BatchStatus.PENDING)
    work_items: List[Any] = Field(
        default_factory=list, sa_column=Column(JSONB, default=[])
    )
    items_count: int = 0
    worker_id: Optional[str] = None
    processed_count: int = 0
    success_count: int = 0
    error_count: int = 0
    results: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, default={})
    )
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
