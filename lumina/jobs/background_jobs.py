"""Background job execution without Celery - using threading and database tracking."""

import logging
import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional

from ..db import get_db_context
from ..db.models import Job
from .types import JobContext

logger = logging.getLogger(__name__)

# Configuration
MAX_WORKERS = int(os.getenv("LUMINA_MAX_WORKERS", "3"))
JOB_TIMEOUT_SECONDS = int(os.getenv("LUMINA_JOB_TIMEOUT", str(24 * 3600)))  # 24 hours
MAX_RETRIES = int(os.getenv("LUMINA_JOB_MAX_RETRIES", "3"))
RETRY_DELAY_SECONDS = 5
ORPHANED_JOB_TIMEOUT_MINUTES = 60  # Jobs stuck in PROGRESS for 60+ min are orphaned

# Priority levels for job scheduling
PRIORITY_USER_IMMEDIATE = 100  # User clicked button, blocking UI
PRIORITY_USER_BATCH = 80  # Bulk operations
PRIORITY_WAREHOUSE_CRITICAL = 40  # Critical maintenance
PRIORITY_WAREHOUSE_HIGH = 30  # Low confidence tags
PRIORITY_WAREHOUSE_MEDIUM = 20  # Regular maintenance
PRIORITY_WAREHOUSE_LOW = 10  # Nice-to-have

# Global thread pool for job execution
_executor: Optional[ThreadPoolExecutor] = None
_active_jobs: Dict[str, Future[Any]] = {}
_job_stop_flags: Dict[str, threading.Event] = {}  # Cooperative cancellation
_initialized = False


def get_executor() -> ThreadPoolExecutor:
    """Get or create the global thread pool executor."""
    global _executor, _initialized
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=MAX_WORKERS,
            thread_name_prefix="lumina-job-",
        )
        logger.info(f"Created job executor with {MAX_WORKERS} workers")

        # On first initialization, recover orphaned jobs
        if not _initialized:
            _initialized = True
            _recover_orphaned_jobs()

    return _executor


def _recover_orphaned_jobs() -> None:
    """Find and fail jobs that were left in PROGRESS state (orphaned by restart)."""
    try:
        with get_db_context() as db:
            # Find jobs stuck in PROGRESS that haven't been updated recently
            cutoff_time = datetime.utcnow() - timedelta(
                minutes=ORPHANED_JOB_TIMEOUT_MINUTES
            )

            orphaned = (
                db.query(Job)
                .filter(Job.status == "PROGRESS", Job.created_at < cutoff_time)
                .all()
            )

            for job in orphaned:
                logger.warning(f"Recovering orphaned job {job.id}")
                job.status = "FAILURE"
                job.error = "Job orphaned (container restart or crash)"
                job.completed_at = datetime.utcnow()

            if orphaned:
                db.commit()
                logger.info(f"Recovered {len(orphaned)} orphaned jobs")

    except Exception as e:
        logger.error(f"Failed to recover orphaned jobs: {e}")


def create_job(
    db_session: Any,
    job_type: str,
    catalog_id: str,
    parameters: Dict[str, Any],
    job_source: str = "user",
    priority: int = 50,
    warehouse_trigger: Optional[str] = None,
) -> Job:
    """Create a job record in the database.

    Args:
        db_session: Database session
        job_type: Type of job (scan, detect_duplicates, etc.)
        catalog_id: Catalog ID
        parameters: Job parameters
        job_source: Source of job ('user' or 'warehouse')
        priority: Job priority (0-100, higher = more urgent)
        warehouse_trigger: Description of what triggered warehouse job

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
        job_source=job_source,
        priority=priority,
        warehouse_trigger=warehouse_trigger,
        scheduled_at=datetime.utcnow() if job_source == "warehouse" else None,
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
        with get_db_context() as db:
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
    func: Callable[[JobContext], Any],
    ctx: JobContext,
) -> Any:
    """Execute job function with retry logic.

    Args:
        job_id: Job ID
        func: Function to execute (accepts JobContext)
        ctx: Job context

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
            result = func(ctx)
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


def should_stop_job(job_id: str) -> bool:
    """Check if job has been requested to stop (cooperative cancellation).

    Job implementations should periodically call this and gracefully exit if True.

    Args:
        job_id: Job ID to check

    Returns:
        True if job should stop execution
    """
    stop_flag = _job_stop_flags.get(job_id)
    return stop_flag is not None and stop_flag.is_set()


def has_active_job(catalog_id: str, job_type: str) -> bool:
    """Check if there's already a PENDING or PROGRESS job of the same type for this catalog.

    Args:
        catalog_id: Catalog ID
        job_type: Job type string

    Returns:
        True if an active job of the same type exists
    """
    try:
        with get_db_context() as db:
            existing = (
                db.query(Job)
                .filter(
                    Job.catalog_id == catalog_id,
                    Job.job_type == job_type,
                    Job.status.in_(["PENDING", "PROGRESS"]),
                )
                .first()
            )
            return existing is not None
    except Exception as e:
        logger.error(f"Failed to check for active job: {e}")
        return False


def _trigger_chained_jobs(job_id: str, ctx: JobContext) -> None:
    """After a job succeeds, submit any jobs that were chained to run after it."""
    try:
        with get_db_context() as db:
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job or not job.parameters:
                return
            chained = job.parameters.get("_chained_jobs", [])

        if not chained:
            return

        from .job_implementations import JOB_FUNCTIONS  # lazy import to avoid circular

        for spec in chained:
            job_type = spec.get("job_type")
            catalog_id = spec.get("catalog_id", ctx.catalog_id)
            params = spec.get("parameters", {})
            source = spec.get("job_source", "user")
            priority = spec.get("priority", 100)
            trigger = spec.get("warehouse_trigger")

            if job_type not in JOB_FUNCTIONS:
                logger.warning(f"Chained job type '{job_type}' not found, skipping")
                continue

            with get_db_context() as db:
                chained_job = create_job(
                    db,
                    job_type=job_type,
                    catalog_id=catalog_id,
                    parameters=params,
                    job_source=source,
                    priority=priority,
                    warehouse_trigger=trigger,
                )
                chained_job_id = chained_job.id

            logger.info(
                f"Triggering chained job {job_type} (id={chained_job_id}) after {job_id}"
            )
            run_job_in_background(
                job_id=chained_job_id,
                catalog_id=catalog_id,
                func=JOB_FUNCTIONS[job_type],
                parameters=params,
            )

    except Exception as e:
        logger.error(f"Failed to trigger chained jobs after {job_id}: {e}")


def run_job_in_background(
    job_id: str,
    catalog_id: str,
    func: Callable[[JobContext], Any],
    parameters: Dict[str, Any],
) -> None:
    """Run a job function in a background thread with fault tolerance.

    Features:
    - ThreadPoolExecutor for resource limiting
    - Automatic retry for transient failures
    - Cooperative cancellation via should_stop_job()
    - Timeout handling
    - Proper error logging and status updates
    - Tracks active jobs in memory for monitoring

    Args:
        job_id: Job ID
        catalog_id: Catalog ID
        func: Function to execute (accepts JobContext)
        parameters: Job parameters
    """
    executor = get_executor()

    # Create stop flag for cooperative cancellation
    _job_stop_flags[job_id] = threading.Event()

    # Create job context
    ctx = JobContext(
        job_id=job_id,
        catalog_id=catalog_id,
        parameters=parameters,
    )

    def _job_wrapper() -> Any:
        """Wrapper that handles execution, retries, and cleanup."""
        try:
            # Check if cancelled before starting
            if should_stop_job(job_id):
                logger.info(f"Job {job_id} cancelled before execution")
                update_job_status(job_id, "FAILURE", error="Job cancelled by user")
                return None

            result = _execute_job_with_retry(job_id, func, ctx)

            # Check if cancelled during execution
            if should_stop_job(job_id):
                logger.info(f"Job {job_id} cancelled during execution")
                update_job_status(job_id, "FAILURE", error="Job cancelled by user")
                return None

            update_job_status(job_id, "SUCCESS", result=result or {})

            # Trigger any chained jobs that were waiting on this one
            _trigger_chained_jobs(job_id, ctx)

            return result

        except Exception as e:
            logger.exception(f"Job {job_id} failed after all retries")
            update_job_status(job_id, "FAILURE", error=str(e))
            raise

        finally:
            # Cleanup
            _active_jobs.pop(job_id, None)
            _job_stop_flags.pop(job_id, None)

    # Submit to thread pool
    future = executor.submit(_job_wrapper)
    _active_jobs[job_id] = future

    logger.info(
        f"Job {job_id} submitted to executor (active jobs: {len(_active_jobs)})"
    )


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Get job status from database.

    Args:
        job_id: Job ID

    Returns:
        Job status dict or None if not found
    """
    try:
        with get_db_context() as db:
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
                    "job_source": job.job_source,
                    "priority": job.priority,
                    "warehouse_trigger": job.warehouse_trigger,
                }
    except Exception as e:
        logger.error(f"Failed to get job {job_id} status: {e}")
    return None


def cancel_job(job_id: str) -> bool:
    """Cancel a running job using cooperative cancellation.

    This sets a stop flag that job implementations can check via should_stop_job().
    For jobs that don't check the flag, attempts to cancel the future.

    Args:
        job_id: Job ID to cancel

    Returns:
        True if cancellation was initiated, False otherwise
    """
    # Set stop flag for cooperative cancellation
    stop_flag = _job_stop_flags.get(job_id)
    if stop_flag:
        logger.info(f"Setting stop flag for job {job_id}")
        stop_flag.set()

    # Try to cancel the future (only works if not yet started)
    future = _active_jobs.get(job_id)
    if future:
        cancelled = future.cancel()
        if cancelled:
            logger.info(f"Cancelled future for job {job_id}")
            update_job_status(job_id, "FAILURE", error="Job cancelled by user")
            _active_jobs.pop(job_id, None)
            _job_stop_flags.pop(job_id, None)
            return True
        else:
            # Already running, cooperative cancellation will handle it
            logger.info(
                f"Job {job_id} already running, cooperative cancellation in progress"
            )
            update_job_status(
                job_id,
                "PROGRESS",
                progress={"phase": "cancelling", "message": "Cancellation requested"},
            )
            return True

    # Job not in active list, mark as cancelled in DB
    logger.info(f"Job {job_id} not active, marking as cancelled in database")
    update_job_status(job_id, "FAILURE", error="Job cancelled by user")
    return True


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
