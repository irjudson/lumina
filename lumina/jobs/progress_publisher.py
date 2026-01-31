"""Database-based progress publisher for job updates.

This module provides a simple, reliable way to publish job progress updates
via PostgreSQL database with LISTEN/NOTIFY for real-time features.
The frontend can either:
1. Subscribe to PostgreSQL channel for real-time updates (WebSocket)
2. Poll the last progress from database table (REST endpoint)

The key design goals are:
- Never block: all operations have short timeouts
- Fail gracefully: if database is unavailable, operations silently fail
- Simple REST polling: frontend can poll every 1-2s without hanging
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..db.connection import SessionLocal

logger = logging.getLogger(__name__)


def get_progress_channel(job_id: str) -> str:
    """Get PostgreSQL NOTIFY channel name for a job."""
    return f"job_progress_{job_id}"


def get_progress_table_name() -> str:
    """Get table name for storing job progress."""
    # Use a single table with job_id as key for simplicity
    return "job_progress"


def publish_progress(
    job_id: str,
    state: str,
    current: int = 0,
    total: int = 0,
    message: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Publish job progress to database.

    This:
    1. Stores progress in job_progress table (for polling)
    2. Sends PostgreSQL NOTIFY (for real-time subscribers)

    Args:
        job_id: The Celery task ID
        state: Current state (PENDING, PROGRESS, SUCCESS, FAILURE)
        current: Current progress count
        total: Total items to process
        message: Human-readable progress message
        extra: Additional metadata

    Returns:
        True if published successfully, False otherwise
    """
    try:
        session = SessionLocal()
        try:
            # Build progress payload
            progress_data: Dict[str, Any] = {
                "current": current,
                "total": total,
                "percent": int((current / total) * 100) if total > 0 else 0,
                "message": message,
            }
            if extra:
                progress_data.update(extra)

            progress: Dict[str, Any] = {
                "job_id": job_id,
                "status": state,
                "progress": progress_data,
                "timestamp": datetime.utcnow().isoformat(),
            }

            payload = json.dumps(progress)

            # Store progress in database (upsert)
            session.execute(
                text(
                    "INSERT INTO job_progress (job_id, progress_data, updated_at) VALUES (:job_id, :payload, NOW()) ON CONFLICT (job_id) DO UPDATE SET progress_data = :payload, updated_at = NOW()"
                ),
                {"job_id": job_id, "payload": payload},
            )

            # Send NOTIFY for real-time subscribers
            channel_name = get_progress_channel(job_id)
            session.execute(text(f"NOTIFY {channel_name}, '{payload}'"))

            session.commit()
            logger.debug(
                f"Published progress for job {job_id}: {state} {current}/{total}"
            )
            return True

        except SQLAlchemyError as e:
            session.rollback()
            raise e
        finally:
            session.close()

    except Exception as e:
        logger.warning(f"Failed to publish progress for job {job_id}: {e}")
        return False


def publish_completion(
    job_id: str,
    state: str,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> bool:
    """
    Publish job completion (SUCCESS or FAILURE) to database.

    Args:
        job_id: The Celery task ID
        state: Final state (SUCCESS or FAILURE)
        result: Job result data (for SUCCESS)
        error: Error message (for FAILURE)

    Returns:
        True if published successfully, False otherwise
    """
    try:
        session = SessionLocal()
        try:
            # Build completion payload
            completion: Dict[str, Any] = {
                "job_id": job_id,
                "status": state,
                "timestamp": datetime.utcnow().isoformat(),
            }

            if state == "SUCCESS" and result:
                completion["result"] = result
            elif state == "FAILURE" and error:
                completion["result"] = {"error": error}

            payload = json.dumps(completion)

            # Store final state
            session.execute(
                text(
                    "INSERT INTO job_progress (job_id, progress_data, updated_at) VALUES (:job_id, :payload, NOW()) ON CONFLICT (job_id) DO UPDATE SET progress_data = :payload, updated_at = NOW()"
                ),
                {"job_id": job_id, "payload": payload},
            )

            # Send NOTIFY
            channel_name = get_progress_channel(job_id)
            session.execute(text(f"NOTIFY {channel_name}, '{payload}'"))

            session.commit()
            logger.debug(f"Published completion for job {job_id}: {state}")
            return True

        except SQLAlchemyError as e:
            session.rollback()
            raise e
        finally:
            session.close()

    except Exception as e:
        logger.warning(f"Failed to publish completion for job {job_id}: {e}")
        return False


def get_last_progress(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the last progress update for a job (for REST polling).

    This is a non-blocking operation with a short timeout.

    Args:
        job_id: The Celery task ID

    Returns:
        Progress dict if available, None otherwise
    """
    try:
        session = SessionLocal()
        try:
            result = session.execute(
                text(
                    f"""
                    SELECT progress_data
                    FROM {get_progress_table_name()}
                    WHERE job_id = :job_id
                    """
                ),
                {"job_id": job_id},
            ).fetchone()

            if result and result[0]:
                return json.loads(result[0])
            return None

        finally:
            session.close()

    except Exception as e:
        logger.warning(f"Failed to get progress for job {job_id}: {e}")
        return None


def clear_progress(job_id: str) -> bool:
    """
    Clear progress data for a job (cleanup after job completion).

    Args:
        job_id: The Celery task ID

    Returns:
        True if cleared successfully, False otherwise
    """
    try:
        session = SessionLocal()
        try:
            session.execute(
                text(f"DELETE FROM {get_progress_table_name()} WHERE job_id = :job_id"),
                {"job_id": job_id},
            )
            session.commit()
            return True

        except SQLAlchemyError as e:
            session.rollback()
            raise e
        finally:
            session.close()

    except Exception as e:
        logger.warning(f"Failed to clear progress for job {job_id}: {e}")
        return False


class ProgressSubscriber:
    """
    PostgreSQL LISTEN/NOTIFY subscriber for real-time job progress.

    This is used by WebSocket handler to get real-time updates.
    All operations have short timeouts to prevent hanging.
    """

    def __init__(self, job_id: str, timeout: float = 1.0):
        """
        Initialize subscriber.

        Args:
            job_id: The job ID to subscribe to
            timeout: Timeout for blocking operations (seconds)
        """
        self.job_id = job_id
        self.timeout = timeout
        self._session: Optional[Session] = None
        self._connection: Optional[Connection] = None

    def __enter__(self) -> "ProgressSubscriber":
        """Start subscription."""
        try:
            self._session = SessionLocal()
            self._connection = self._session.connection()
            self._connection.execute(
                text(f"LISTEN {get_progress_channel(self.job_id)}")
            )
            return self

        except Exception as e:
            logger.warning(
                f"Failed to subscribe to progress for job {self.job_id}: {e}"
            )
            self._cleanup()
            raise

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Stop subscription."""
        self._cleanup()

    def _cleanup(self) -> None:
        """Clean up database connection."""
        try:
            if self._connection:
                self._connection.execute(
                    text(f"UNLISTEN {get_progress_channel(self.job_id)}")
                )
                self._connection.close()
                self._connection = None
            if self._session:
                self._session.close()
                self._session = None
        except Exception:
            pass  # Ignore cleanup errors

    def get_message(self) -> Optional[Dict[str, Any]]:
        """
        Get the next message from subscription (non-blocking with timeout).

        Returns:
            Progress dict if available, None if no message or timeout
        """
        if not self._connection:
            return None

        try:
            # Use connection.poll() with timeout
            self._connection.connection.poll(timeout=self.timeout)

            # Check if we have any notifications
            if self._connection.connection.notifies:
                notify = self._connection.connection.notifies.pop(0)
                return json.loads(notify.payload)

            return None

        except Exception as e:
            logger.warning(f"Database error getting message for job {self.job_id}: {e}")
            return None


def cleanup_old_progress(max_age_hours: int = 24) -> int:
    """
    Clean up old progress data to prevent table bloat.

    Args:
        max_age_hours: Maximum age in hours for progress data

    Returns:
        Number of rows cleaned up
    """
    try:
        session = SessionLocal()
        try:
            result = session.execute(
                text(
                    f"""
                    DELETE FROM {get_progress_table_name()}
                    WHERE updated_at < NOW() - INTERVAL '{max_age_hours} hours'
                    """
                )
            )
            session.commit()
            cleaned = result.rowcount  # type: ignore[attr-defined]
            if cleaned > 0:
                logger.info(f"Cleaned up {cleaned} old progress records")
            return cleaned

        except SQLAlchemyError as e:
            session.rollback()
            raise e
        finally:
            session.close()

    except Exception as e:
        logger.warning(f"Failed to cleanup old progress data: {e}")
        return 0
