"""Integration tests for JobExecutor with database."""

import pytest

from lumina.jobs.framework import JobExecutorWithDB, ParallelJob


def test_executor_with_db_accepts_session_factory():
    """JobExecutorWithDB should accept a session factory."""

    def discover(catalog_id: str) -> list:
        return ["a", "b"]

    def process(item: str, **kwargs) -> dict:
        return {"item": item}

    job = ParallelJob(
        name="db_test",
        discover=discover,
        process=process,
    )

    # Mock session factory
    def mock_session_factory():
        return None

    executor = JobExecutorWithDB(job, mock_session_factory)
    assert executor.db_session_factory == mock_session_factory


def test_executor_with_db_runs_job():
    """JobExecutorWithDB should still execute jobs correctly."""
    processed = []

    def discover(catalog_id: str) -> list:
        return ["x", "y"]

    def process(item: str, **kwargs) -> dict:
        processed.append(item)
        return {"item": item}

    job = ParallelJob(
        name="db_run_test",
        discover=discover,
        process=process,
    )

    executor = JobExecutorWithDB(job, lambda: None)
    result = executor.run(job_id="j1", catalog_id="c1")

    assert set(processed) == {"x", "y"}
    assert result["success_count"] == 2


@pytest.mark.integration
def test_executor_tracks_progress_in_db(db_session):
    """Executor should create JobBatch records."""
    # This test requires actual database - placeholder for future
    pass
