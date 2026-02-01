"""Background job execution without Celery - using threading and database tracking."""

import logging
import threading
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from ..db import get_db
from ..db.models import Job

logger = logging.getLogger(__name__)

# Global registry of background jobs
_active_jobs: Dict[str, threading.Thread] = {}


def create_job(
    db_session: Any,
    job_type: str,
    catalog_id: str,
    parameters: Dict[str, Any],
) -> Job:
    """Create a job record in the database."""
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
    """Update job status in database."""
    with next(get_db()) as db:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = status
            if progress:
                job.progress = progress
            if result:
                job.result = result
            if error:
                job.error = error
            if status in ("SUCCESS", "FAILURE"):
                job.completed_at = datetime.utcnow()
            db.commit()


def run_job_in_background(
    job_id: str,
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> None:
    """Run a job function in a background thread."""

    def _wrapper() -> None:
        try:
            update_job_status(job_id, "PROGRESS")
            result = func(*args, job_id=job_id, **kwargs)
            update_job_status(job_id, "SUCCESS", result=result or {})
        except Exception as e:
            logger.exception(f"Job {job_id} failed")
            update_job_status(job_id, "FAILURE", error=str(e))
        finally:
            # Remove from active jobs
            _active_jobs.pop(job_id, None)

    thread = threading.Thread(target=_wrapper, daemon=True)
    _active_jobs[job_id] = thread
    thread.start()


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Get job status from database."""
    with next(get_db()) as db:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            return {
                "id": job.id,
                "status": job.status,
                "progress": job.progress,
                "result": job.result,
                "error": job.error,
            }
    return None
