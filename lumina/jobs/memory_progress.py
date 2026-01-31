"""In-memory progress tracking for self-contained Lumina application.

This module provides simple, in-memory progress tracking without requiring
database persistence or external services. It's designed for scenarios where
the application needs to run in environments without database setup
or where Redis dependency removal is desired for maximum simplicity.

The design prioritizes:
1. No external dependencies (Redis, PostgreSQL broker)
2. Simple in-memory data structures
3. Thread-safe operations for concurrent access
4. Fallback options for enhanced functionality
5. Clean separation of concerns
"""

import logging
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# In-memory progress storage
_progress_storage: Dict[str, Dict[str, Any]] = {}
_progress_locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)


def get_progress_lock(job_id: str) -> threading.Lock:
    """Get or create a lock for job-specific progress."""
    if job_id not in _progress_locks:
        _progress_locks[job_id] = threading.Lock()
    return _progress_locks[job_id]


def update_progress(
    job_id: str,
    state: str,
    current: int = 0,
    total: int = 0,
    message: str = "",
    extra: Optional[Dict[str, Any]] = None,
    timestamp: Optional[datetime] = None,
) -> bool:
    """
    Update job progress in memory.

    Thread-safe implementation using per-job locks.

    Args:
        job_id: The Celery task ID
        state: Current state (PENDING, PROGRESS, SUCCESS, FAILURE)
        current: Current progress count
        total: Total items to process
        message: Human-readable progress message
        extra: Additional metadata
        timestamp: Timestamp of update

    Returns:
        True if updated successfully, False otherwise
    """
    try:
        with get_progress_lock(job_id):
            # Build progress data
            progress_data: Dict[str, Any] = {
                "current": current,
                "total": total,
                "percent": int((current / total) * 100) if total > 0 else 0,
                "message": message,
            }

            if extra:
                progress_data.update(extra)

            progress_entry: Dict[str, Any] = {
                "status": state,
                "progress": progress_data,
                "timestamp": timestamp or datetime.utcnow().isoformat(),
            }

            _progress_storage[job_id] = progress_entry

            logger.debug(
                f"Updated progress for job {job_id}: {state} {current}/{total}"
            )
            return True

    except Exception as e:
        logger.warning(f"Failed to update progress for job {job_id}: {e}")
        return False


def get_last_progress(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the last progress update for a job from memory.

    Args:
        job_id: The Celery task ID

    Returns:
        Progress dict if available, None otherwise
    """
    with get_progress_lock(job_id):
        return _progress_storage.get(job_id)


def track_job_in_memory(
    job_id: str,
    job_type: str,
    params: Dict[str, Any],
    catalog_id: Optional[str] = None,
) -> bool:
    """
    Track job in memory (fallback when database unavailable).

    Args:
        job_id: The Celery task ID
        job_type: Type of job
        params: Job parameters
        catalog_id: Optional catalog ID

    Returns:
        True if tracked successfully, False otherwise
    """
    try:
        with get_progress_lock(job_id):
            job_data = {
                "job_id": job_id,
                "type": job_type,
                "params": params,
                "catalog_id": catalog_id,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }

            # Store in global in-memory tracker
            _progress_storage[job_id] = job_data

            logger.debug(f"Tracked job {job_id} of type {job_type} in memory")
            return True

    except Exception as e:
        logger.warning(f"Failed to track job {job_id} in memory: {e}")
        return False


def get_recent_jobs_in_memory(limit: int = 50) -> list:
    """
    Get recent jobs from memory (sorted by creation time).

    Args:
        limit: Maximum number of jobs to return

    Returns:
        List of recent job dictionaries
    """
    try:
        # Get all jobs and sort by creation time
        all_jobs = [job_data for job_data in _progress_storage.values()]

        # Sort by created_at (newest first)
        all_jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        # Return limited list
        return all_jobs[:limit]

    except Exception as e:
        logger.warning(f"Failed to get recent jobs from memory: {e}")
        return []


def cleanup_old_in_memory(max_age_hours: int = 24) -> int:
    """
    Clean up old job data from memory.

    Args:
        max_age_hours: Maximum age in hours for data retention

    Returns:
        Number of jobs cleaned up
    """
    try:
        cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
        cleaned_count = 0

        with get_progress_lock("cleanup"):
            jobs_to_remove = []
            for job_id, job_data in list(_progress_storage.items()):
                if job_id == "cleanup":
                    continue
                created_at = datetime.fromisoformat(job_data.get("created_at", ""))
                if created_at and created_at < cutoff_time:
                    jobs_to_remove.append(job_id)
                    del _progress_storage[job_id]
                    cleaned_count += 1

            logger.info(f"Cleaned up {cleaned_count} old jobs from memory")
            return cleaned_count

    except Exception as e:
        logger.warning(f"Failed to cleanup old jobs from memory: {e}")
        return 0


def get_in_memory_stats() -> Dict[str, int]:
    """Get statistics about in-memory job tracking."""
    stats: Dict[str, int] = defaultdict(int)
    for job_data in _progress_storage.values():
        if job_data.get("type"):
            stats[job_data["type"]] += 1
    return dict(stats)


# Fallback manager that chooses between database and in-memory
class ProgressManager:
    """Manages progress updates with fallback to in-memory storage."""

    def __init__(self, use_in_memory: bool = False):
        """Initialize progress manager.

        Args:
            use_in_memory: Force in-memory mode (for testing/Redis-free env)
        """
        self.use_in_memory = use_in_memory

    def update_progress(
        self,
        job_id: str,
        state: str,
        current: int = 0,
        total: int = 0,
        message: str = "",
        extra: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
    ) -> bool:
        """Update progress using appropriate backend."""
        if self.use_in_memory:
            return update_progress(
                job_id, state, current, total, message, extra, timestamp
            )
        else:
            # Use database progress publisher
            from lumina.jobs.db_progress_publisher import update_progress as db_update

            return db_update(job_id, state, current, total, message, extra, timestamp)

    def get_last_progress(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get last progress using appropriate backend."""
        if self.use_in_memory:
            return get_last_progress(job_id)
        else:
            # Use database progress publisher
            from lumina.jobs.db_progress_publisher import get_last_progress as db_get

            return db_get(job_id)

    def track_job(
        self,
        job_id: str,
        job_type: str,
        params: Dict[str, Any],
        catalog_id: Optional[str] = None,
    ) -> None:
        """Track job using appropriate backend."""
        if self.use_in_memory:
            track_job_in_memory(job_id, job_type, params, catalog_id)
        else:
            # Use database job history
            from lumina.jobs.job_history import track_job as db_track

            db_track(job_id, job_type, params)

    def get_recent_jobs(self, limit: int = 50) -> list[Dict[str, Any]]:
        """Get recent jobs using appropriate backend."""
        if self.use_in_memory:
            return get_recent_jobs_in_memory(limit)
        else:
            # Use database job history
            from lumina.jobs.job_history import get_recent_jobs as db_get

            return db_get(limit)

    def get_in_memory_stats(self) -> Dict[str, int]:
        """Get in-memory statistics."""
        if self.use_in_memory:
            return get_in_memory_stats()
        else:
            # Use database job history stats
            from lumina.jobs.job_history import get_job_history_stats as db_get

            return db_get()


# Global progress manager instance
progress_manager = ProgressManager(use_in_memory=False)
