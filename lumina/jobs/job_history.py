"""Database-based job history management to replace Redis tracking."""

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..db.connection import SessionLocal

logger = logging.getLogger(__name__)

# Maximum number of recent jobs to keep in history
MAX_HISTORY_SIZE = 100


def track_job(job_id: str, job_type: str, params: dict) -> None:
    """
    Track job submission in database for history.

    This replaces Redis-based job tracking with database storage.

    Args:
        job_id: The Celery task ID
        job_type: Type of job (analyze_catalog, organize_catalog, etc.)
        params: Job parameters as dictionary
    """
    try:
        session = SessionLocal()
        try:
            # Convert parameters to JSON string for storage
            params_json = json.dumps(params)

            # Insert job record with parameters
            session.execute(
                text(
                    """
                    INSERT INTO jobs (id, job_type, parameters, status, created_at, updated_at)
                    VALUES (:job_id, :job_type, :parameters, 'PENDING', NOW(), NOW())
                    ON CONFLICT (id)
                    DO UPDATE SET
                        parameters = :parameters,
                        updated_at = NOW()
                    """
                ),
                {"job_id": job_id, "job_type": job_type, "parameters": params_json},
            )

            session.commit()
            logger.debug(f"Tracked job {job_id} of type {job_type} in database")

        except SQLAlchemyError as e:
            session.rollback()
            raise e
        finally:
            session.close()

    except Exception as e:
        logger.warning(f"Failed to track job {job_id}: {e}")


def get_recent_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get list of recent jobs for history display.

    This replaces Redis lrange operation with database query.

    Args:
        limit: Maximum number of jobs to return

    Returns:
        List of job dictionaries with id, type, params, submitted_at
    """
    try:
        session = SessionLocal()
        try:
            result = session.execute(
                text(
                    """
                    SELECT id, job_type, parameters, created_at, updated_at, status
                    FROM jobs
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )

            jobs = []
            for row in result.fetchall():
                job = {
                    "job_id": row[0],
                    "type": row[1],
                    "params": json.loads(row[2]) if row[2] else {},
                    "submitted_at": row[3].isoformat() if row[3] else None,
                    "status": row[4] or "PENDING",
                }
                jobs.append(job)

            return jobs

        finally:
            session.close()

    except Exception as e:
        logger.warning(f"Failed to get recent jobs: {e}")
        return []


def get_job_params(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Get original parameters for a job (for rerun functionality).

    This replaces Redis get operation with database query.

    Args:
        job_id: The Celery task ID

    Returns:
        Job parameters dictionary if found, None otherwise
    """
    try:
        session = SessionLocal()
        try:
            result = session.execute(
                text(
                    """
                    SELECT job_type, parameters
                    FROM jobs
                    WHERE id = :job_id
                    """
                ),
                {"job_id": job_id},
            ).fetchone()

            if result:
                job_type, params_json = result
                if params_json:
                    return {"type": job_type, "params": json.loads(params_json)}

            return None

        finally:
            session.close()

    except Exception as e:
        logger.warning(f"Failed to get job params for {job_id}: {e}")
        return None


def cleanup_old_jobs(max_age_hours: int = 24) -> int:
    """
    Clean up old job records to prevent table bloat.

    This replaces Redis TTL functionality with manual cleanup.

    Args:
        max_age_hours: Maximum age in hours for job records

    Returns:
        Number of jobs cleaned up
    """
    try:
        session = SessionLocal()
        try:
            result = session.execute(
                text(
                    """
                    DELETE FROM jobs
                    WHERE updated_at < NOW() - INTERVAL ':max_age_hours hours'
                    AND status IN ('SUCCESS', 'FAILURE', 'REVOKED')
                    """
                ),
                {"max_age_hours": max_age_hours},
            )
            session.commit()
            cleaned = result.rowcount  # type: ignore[attr-defined]
            if cleaned > 0:
                logger.info(f"Cleaned up {cleaned} old job records")
            return cleaned

        except SQLAlchemyError as e:
            session.rollback()
            raise e
        finally:
            session.close()

    except Exception as e:
        logger.warning(f"Failed to cleanup old jobs: {e}")
        return 0


def get_job_history_stats() -> Dict[str, int]:
    """
    Get statistics about job history.

    Returns:
        Dictionary with job counts by status
    """
    try:
        session = SessionLocal()
        try:
            result = session.execute(
                text(
                    """
                    SELECT status, COUNT(*) as count
                    FROM jobs
                    GROUP BY status
                    """
                )
            )

            stats = {}
            for row in result.fetchall():
                status, count = row
                stats[status.lower()] = count

            return stats

        finally:
            session.close()

    except Exception as e:
        logger.warning(f"Failed to get job history stats: {e}")
        return {}
