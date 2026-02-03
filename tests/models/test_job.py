"""Tests for Job and JobBatch models."""

import uuid

from lumina.models.job import BatchStatus, Job, JobBatch, JobStatus


def test_job_status_enum():
    """JobStatus should have standard states."""
    assert JobStatus.PENDING.value == "pending"
    assert JobStatus.RUNNING.value == "running"
    assert JobStatus.SUCCESS.value == "success"
    assert JobStatus.FAILED.value == "failed"
    assert JobStatus.CANCELLED.value == "cancelled"


def test_batch_status_enum():
    """BatchStatus should have workflow states."""
    assert BatchStatus.PENDING.value == "pending"
    assert BatchStatus.RUNNING.value == "running"
    assert BatchStatus.COMPLETED.value == "completed"
    assert BatchStatus.FAILED.value == "failed"
    assert BatchStatus.CANCELLED.value == "cancelled"


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
    assert job.progress == {}
    assert job.result == {}


def test_job_batch_creation():
    """JobBatch should track batch work items."""
    batch = JobBatch(
        parent_job_id="job-123",
        catalog_id=uuid.uuid4(),
        batch_number=1,
        total_batches=4,
        job_type="scan",
    )
    assert batch.id is not None
    assert batch.status == BatchStatus.PENDING
    assert batch.work_items == []
    assert batch.processed_count == 0
