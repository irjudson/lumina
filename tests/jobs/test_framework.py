"""Tests for generic job framework."""

from typing import List

from lumina.jobs.framework import JobRegistry, ParallelJob


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
