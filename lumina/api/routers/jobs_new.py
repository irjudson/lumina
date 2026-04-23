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


# --- Prerequisites ---
# Maps job_type → list of prerequisite specs.
# Each spec: {prereq_type, check, description}
# check(catalog_id, db) → (is_satisfied: bool, detail: str)


def _check_hashes_complete(catalog_id: str, db: Session):
    """Returns (satisfied, detail) for hash_images_v2 prerequisite."""
    from ...db.models import Image

    missing = (
        db.query(Image)
        .filter(
            Image.catalog_id == catalog_id,
            Image.dhash_16.is_(None),
            Image.file_type != "video",
        )
        .count()
    )
    if missing == 0:
        return True, "All images hashed"
    return False, f"{missing:,} images need perceptual hashing"


JOB_PREREQUISITES: dict = {
    "detect_duplicates_v2": [
        {
            "prereq_type": "hash_images_v2",
            "check": _check_hashes_complete,
            "description": "Perceptual hashing",
        }
    ]
}


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


class PrerequisiteInfo(BaseModel):
    """Info about a prerequisite job that was auto-submitted."""

    prereq_job_id: str
    prereq_job_type: str
    description: str
    detail: str  # e.g. "74,450 images need perceptual hashing"
    chained_job_type: str  # the original job that will run after


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
    prerequisite: Optional[PrerequisiteInfo] = None

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

    # Check prerequisites
    prereqs = JOB_PREREQUISITES.get(request.job_type, [])
    for prereq in prereqs:
        satisfied, detail = prereq["check"](request.catalog_id, db)
        if not satisfied:
            prereq_type = prereq["prereq_type"]
            description = prereq["description"]

            # Don't submit duplicate prereq if already running
            if has_active_job(request.catalog_id, prereq_type):
                raise HTTPException(
                    status_code=409,
                    detail=f"Prerequisite '{prereq_type}' is already running. "
                    f"{request.job_type} will need to be resubmitted after it completes.",
                )

            # Submit the prerequisite job, chaining the original job after it
            chained_spec = {
                "job_type": request.job_type,
                "catalog_id": str(request.catalog_id),
                "parameters": request.parameters,
                "job_source": request.job_source,
                "priority": request.priority,
                "warehouse_trigger": f"Auto-started after {prereq_type} (prerequisite)",
            }
            prereq_params = {"_chained_jobs": [chained_spec]}

            prereq_job = create_job(
                db,
                job_type=prereq_type,
                catalog_id=request.catalog_id,
                parameters=prereq_params,
                job_source=request.job_source,
                priority=request.priority,
                warehouse_trigger=f"Prerequisite for {request.job_type}: {description} — {detail}",
            )
            prereq_func = JOB_FUNCTIONS[prereq_type]
            run_job_in_background(
                job_id=prereq_job.id,
                catalog_id=str(request.catalog_id),
                func=prereq_func,
                parameters=prereq_params,
            )

            logger.info(
                f"Submitted prerequisite {prereq_type} (id={prereq_job.id}) "
                f"before {request.job_type}: {detail}"
            )
            return JobResponse(
                id=prereq_job.id,
                job_type=prereq_job.job_type,
                catalog_id=(
                    str(prereq_job.catalog_id) if prereq_job.catalog_id else None
                ),
                status=JobResponse._normalize_status(prereq_job.status),
                progress=prereq_job.progress,
                job_source=prereq_job.job_source,
                priority=prereq_job.priority,
                warehouse_trigger=prereq_job.warehouse_trigger,
                created_at=(
                    prereq_job.created_at.isoformat() if prereq_job.created_at else None
                ),
                prerequisite=PrerequisiteInfo(
                    prereq_job_id=prereq_job.id,
                    prereq_job_type=prereq_type,
                    description=description,
                    detail=detail,
                    chained_job_type=request.job_type,
                ),
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
    job_source: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List jobs. Optionally filter by job_source ('user' or 'warehouse')."""
    query = db.query(Job)
    if catalog_id:
        query = query.filter(Job.catalog_id == catalog_id)
    if job_source:
        query = query.filter(Job.job_source == job_source)

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
