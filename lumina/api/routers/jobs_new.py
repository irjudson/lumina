"""Jobs API router - migrated from Celery to FastAPI BackgroundTasks."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db import get_db
from ...db.models import Job
from ...jobs.background_jobs import cancel_job as cancel_job_bg
from ...jobs.background_jobs import create_job, has_active_job, run_job_in_background
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
    job_source: str = "user"  # 'user' or 'warehouse'
    priority: int = 100  # Default to high priority for user jobs
    warehouse_trigger: Optional[str] = None


class JobResponse(BaseModel):
    """Job response."""

    id: str
    job_type: Optional[str] = None
    catalog_id: Optional[str] = None
    status: str
    progress: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    job_source: Optional[str] = "user"
    priority: Optional[int] = 50
    warehouse_trigger: Optional[str] = None
    created_at: Optional[str] = None

    @staticmethod
    def _normalize_status(status: str) -> str:
        """Convert backend status to frontend format (lowercase)."""
        status_map = {
            "PENDING": "pending",
            "PROGRESS": "running",
            "SUCCESS": "success",
            "FAILURE": "failure",
        }
        return status_map.get(status, status.lower())


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

    # Verify catalog exists
    from ...db.models import Catalog

    catalog = db.query(Catalog).filter(Catalog.id == request.catalog_id).first()
    if not catalog:
        raise HTTPException(status_code=404, detail="Catalog not found")

    # Check for duplicate active job
    if has_active_job(request.catalog_id, request.job_type):
        raise HTTPException(
            status_code=409,
            detail=f"A {request.job_type} job is already pending or running for this catalog",
        )

    # Create job record
    job = create_job(
        db,
        job_type=request.job_type,
        catalog_id=request.catalog_id,
        parameters=request.parameters,
        job_source=request.job_source,
        priority=request.priority,
        warehouse_trigger=request.warehouse_trigger,
    )

    # Get job function
    job_func = JOB_FUNCTIONS[request.job_type]

    # All jobs use the same standardized interface now
    run_job_in_background(
        job_id=job.id,
        catalog_id=str(request.catalog_id),
        func=job_func,
        parameters=request.parameters,
    )

    return JobResponse(
        id=job.id,
        job_type=job.job_type,
        catalog_id=str(job.catalog_id) if job.catalog_id else None,
        status=JobResponse._normalize_status(job.status),
        progress=job.progress,
        job_source=job.job_source,
        priority=job.priority,
        warehouse_trigger=job.warehouse_trigger,
        created_at=job.created_at.isoformat() if job.created_at else None,
    )


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    """Get job status."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobResponse(
        id=job.id,
        job_type=job.job_type,
        catalog_id=str(job.catalog_id) if job.catalog_id else None,
        status=JobResponse._normalize_status(job.status),
        progress=job.progress,
        result=job.result,
        error=job.error,
        job_source=job.job_source,
        priority=job.priority,
        warehouse_trigger=job.warehouse_trigger,
        created_at=job.created_at.isoformat() if job.created_at else None,
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
            job_type=job.job_type,
            catalog_id=str(job.catalog_id) if job.catalog_id else None,
            status=JobResponse._normalize_status(job.status),
            progress=job.progress,
            result=job.result,
            error=job.error,
            job_source=job.job_source,
            priority=job.priority,
            warehouse_trigger=job.warehouse_trigger,
            created_at=job.created_at.isoformat() if job.created_at else None,
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

    # Mark as cancelled via the request's db session (ensures test isolation)
    job.status = "FAILURE"
    job.error = "Cancelled by user"
    db.commit()

    # Additionally attempt to stop any running future
    cancel_job_bg(job_id)

    return {"message": "Job cancelled"}
