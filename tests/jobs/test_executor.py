"""Tests for JobExecutor."""

from lumina.jobs.framework import JobExecutor, ParallelJob


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

    executor = JobExecutor(job)
    result = executor.run(
        job_id="job-1",
        catalog_id="cat-1",
    )

    assert set(processed_items) == {"a", "b", "c"}
    assert result["total"] == 3
    assert result["success_count"] == 3
    assert result["error_count"] == 0


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

    executor = JobExecutor(job)
    result = executor.run(job_id="job-2", catalog_id="cat-1")

    assert result["success_count"] == 2
    assert result["error_count"] == 1


def test_executor_empty_items():
    """Executor should handle empty discover result."""

    def discover(catalog_id: str) -> list:
        return []

    def process(item: str, **kwargs) -> dict:
        return {}

    job = ParallelJob(
        name="empty",
        discover=discover,
        process=process,
    )

    executor = JobExecutor(job)
    result = executor.run(job_id="job-3", catalog_id="cat-1")

    assert result["total_items"] == 0
    assert result["success_count"] == 0
