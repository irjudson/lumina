"""Background job execution without Celery - using threading and database tracking."""

import logging
import os
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from ..db import get_db
from ..db.models import Job

logger = logging.getLogger(__name__)

# Configuration
MAX_WORKERS = int(os.getenv("LUMINA_MAX_JOB_WORKERS", "4"))
JOB_TIMEOUT_SECONDS = int(os.getenv("LUMINA_JOB_TIMEOUT", str(24 * 3600)))  # 24 hours
MAX_RETRIES = int(os.getenv("LUMINA_JOB_MAX_RETRIES", "3"))
RETRY_DELAY_SECONDS = 5

# Global thread pool for job execution
_executor: Optional[ThreadPoolExecutor] = None
_active_jobs: Dict[str, Future[Any]] = {}


def get_executor() -> ThreadPoolExecutor:
    """Get or create the global thread pool executor."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=MAX_WORKERS,
            thread_name_prefix="lumina-job-",
        )
        logger.info(f"Created job executor with {MAX_WORKERS} workers")
    return _executor


def create_job(
    db_session: Any,
    job_type: str,
    catalog_id: str,
    parameters: Dict[str, Any],
) -> Job:
    """Create a job record in the database.

    Args:
        db_session: Database session
        job_type: Type of job (scan, detect_duplicates, etc.)
        catalog_id: Catalog ID
        parameters: Job parameters

    Returns:
        Created Job instance
    """
    job = Job(
        id=str(uuid.uuid4()),
        catalog_id=catalog_id,
        job_type=job_type,
        status="PENDING",
        parameters=parameters,
        progress={"current": 0, "total": 0, "percent": 0},
        created_at=datetime.utcnow(),
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def update_job_status(
    job_id: str,
    status: str,
    progress: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    """Update job status in database.

    Args:
        job_id: Job ID
        status: New status (PENDING, PROGRESS, SUCCESS, FAILURE)
        progress: Progress information
        result: Result data (for SUCCESS)
        error: Error message (for FAILURE)
    """
    try:
        with next(get_db()) as db:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = status
                if progress is not None:
                    job.progress = progress
                if result is not None:
                    job.result = result
                if error is not None:
                    job.error = error
                if status in ("SUCCESS", "FAILURE"):
                    job.completed_at = datetime.utcnow()
                db.commit()
    except Exception as e:
        logger.error(f"Failed to update job {job_id} status: {e}")


def _is_retryable_error(error: Exception) -> bool:
    """Check if an error is retryable (transient failure).

    Args:
        error: The exception that occurred

    Returns:
        True if error is likely transient and should be retried
    """
    # Database connection errors
    error_msg = str(error).lower()
    retryable_patterns = [
        "connection",
        "timeout",
        "temporarily unavailable",
        "deadlock",
        "lock",
    ]
    return any(pattern in error_msg for pattern in retryable_patterns)


def _execute_job_with_retry(
    job_id: str,
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Execute job function with retry logic.

    Args:
        job_id: Job ID
        func: Function to execute
        *args: Positional arguments
        **kwargs: Keyword arguments

    Returns:
        Job result

    Raises:
        Exception: If all retries exhausted
    """
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            if attempt > 0:
                logger.info(f"Job {job_id} retry attempt {attempt + 1}/{MAX_RETRIES}")
                time.sleep(RETRY_DELAY_SECONDS * attempt)  # Exponential backoff

            update_job_status(job_id, "PROGRESS")
            result = func(*args, job_id=job_id, **kwargs)
            return result

        except Exception as e:
            last_error = e

            if attempt < MAX_RETRIES - 1 and _is_retryable_error(e):
                logger.warning(
                    f"Job {job_id} failed with retryable error (attempt {attempt + 1}): {e}"
                )
                continue
            else:
                # Not retryable or out of retries
                raise

    # Should never reach here, but just in case
    raise last_error or Exception("Job failed with unknown error")


def run_job_in_background(
    job_id: str,
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> None:
    """Run a job function in a background thread with fault tolerance.

    Features:
    - ThreadPoolExecutor for resource limiting
    - Automatic retry for transient failures
    - Timeout handling
    - Proper error logging and status updates

    Args:
        job_id: Job ID
        func: Function to execute
        *args: Positional arguments
        **kwargs: Keyword arguments
    """
    executor = get_executor()

    def _job_wrapper() -> Any:
        """Wrapper that handles execution, retries, and cleanup."""
        try:
            result = _execute_job_with_retry(job_id, func, *args, **kwargs)
            update_job_status(job_id, "SUCCESS", result=result or {})
            return result

        except Exception as e:
            logger.exception(f"Job {job_id} failed after all retries")
            update_job_status(job_id, "FAILURE", error=str(e))
            raise

        finally:
            # Remove from active jobs
            _active_jobs.pop(job_id, None)

    # Submit to thread pool
    future = executor.submit(_job_wrapper)
    _active_jobs[job_id] = future

    # Add timeout callback (non-blocking)
    def _timeout_handler() -> None:
        """Handle job timeout in background."""
        try:
            future.result(timeout=JOB_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.error(f"Job {job_id} timed out after {JOB_TIMEOUT_SECONDS}s")
            update_job_status(
                job_id,
                "FAILURE",
                error=f"Job timed out after {JOB_TIMEOUT_SECONDS} seconds",
            )
            future.cancel()
        except Exception:
            # Exception already logged by _job_wrapper
            pass

    # Start timeout monitoring in separate thread (non-blocking)
    timeout_thread = executor.submit(_timeout_handler)  # noqa: F841


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Get job status from database.

    Args:
        job_id: Job ID

    Returns:
        Job status dict or None if not found
    """
    try:
        with next(get_db()) as db:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                return {
                    "id": job.id,
                    "status": job.status,
                    "progress": job.progress,
                    "result": job.result,
                    "error": job.error,
                    "created_at": (
                        job.created_at.isoformat() if job.created_at else None
                    ),
                    "completed_at": (
                        job.completed_at.isoformat() if job.completed_at else None
                    ),
                }
    except Exception as e:
        logger.error(f"Failed to get job {job_id} status: {e}")
    return None


def cancel_job(job_id: str) -> bool:
    """Cancel a running job.

    Args:
        job_id: Job ID to cancel

    Returns:
        True if job was cancelled, False otherwise
    """
    future = _active_jobs.get(job_id)
    if future:
        cancelled = future.cancel()
        if cancelled:
            update_job_status(job_id, "FAILURE", error="Job cancelled by user")
            _active_jobs.pop(job_id, None)
            return True
    return False


def get_active_jobs() -> Dict[str, Future[Any]]:
    """Get all currently active jobs.

    Returns:
        Dict mapping job IDs to their Future objects
    """
    return dict(_active_jobs)


def shutdown_executor(wait: bool = True, timeout: Optional[float] = None) -> None:
    """Shutdown the job executor.

    Args:
        wait: If True, wait for running jobs to complete
        timeout: Max seconds to wait (None = wait forever)
    """
    global _executor
    if _executor:
        logger.info(f"Shutting down job executor (wait={wait})")
        _executor.shutdown(wait=wait, cancel_futures=not wait)
        _executor = None
        _active_jobs.clear()
