"""Jobs API router - migrated from Celery to FastAPI BackgroundTasks."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db import get_db
from ...db.models import Job
from ...jobs.background_jobs import cancel_job as cancel_job_bg
from ...jobs.background_jobs import create_job, run_job_in_background
from ...jobs.job_implementations import JOB_FUNCTIONS

logger = logging.getLogger(__name__)

router = APIRouter()


# Health endpoint - must be before parameterized routes
@router.get("/health")
def jobs_health():
    """Jobs system health check."""
    return {"status": "healthy", "backend": "threading"}


class JobSubmitRequest(BaseModel):
    """Job submission request."""

    catalog_id: str
    job_type: str
    parameters: Dict[str, Any] = {}


class JobResponse(BaseModel):
    """Job response."""

    id: str
    status: str
    progress: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@router.post("/submit", response_model=JobResponse)
def submit_job(
    request: JobSubmitRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Submit a new job."""
    if request.job_type not in JOB_FUNCTIONS:
        raise HTTPException(
            status_code=400, detail=f"Unknown job type: {request.job_type}"
        )

    # Create job record
    job = create_job(
        db,
        job_type=request.job_type,
        catalog_id=request.catalog_id,
        parameters=request.parameters,
    )

    # Get job function
    job_func = JOB_FUNCTIONS[request.job_type]

    # Run in background
    run_job_in_background(job.id, job_func, **request.parameters)

    return JobResponse(
        id=job.id,
        status=job.status,
        progress=job.progress,
    )


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    """Get job status."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobResponse(
        id=job.id,
        status=job.status,
        progress=job.progress,
        result=job.result,
        error=job.error,
    )


@router.get("/", response_model=List[JobResponse])
def list_jobs(
    catalog_id: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List jobs."""
    query = db.query(Job)
    if catalog_id:
        query = query.filter(Job.catalog_id == catalog_id)

    jobs = query.order_by(Job.created_at.desc()).limit(limit).all()

    return [
        JobResponse(
            id=job.id,
            status=job.status,
            progress=job.progress,
            result=job.result,
            error=job.error,
        )
        for job in jobs
    ]


@router.delete("/{job_id}")
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    """Cancel a job (note: cancellation may not be immediate)."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in ("SUCCESS", "FAILURE"):
        raise HTTPException(status_code=400, detail="Cannot cancel completed job")

    # Try to cancel the running job
    cancelled = cancel_job_bg(job_id)

    if not cancelled:
        # Job not running or already completed, mark as cancelled in DB
        job.status = "FAILURE"
        job.error = "Cancelled by user"
        db.commit()

    return {"message": "Job cancelled"}
