"""Warehouse scheduler service - background thread that checks catalogs for warehouse tasks."""

import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional

from ..db import get_db_context
from ..db.models import Catalog, WarehouseConfig
from .background_jobs import create_job, has_active_job, run_job_in_background
from .job_implementations import JOB_FUNCTIONS
from .warehouse_tasks import WAREHOUSE_TASKS, assess_task_need

logger = logging.getLogger(__name__)


class WarehouseScheduler:
    """Background scheduler that checks catalogs for warehouse automation tasks."""

    def __init__(self, check_interval_seconds: int = 60):
        """Initialize warehouse scheduler.

        Args:
            check_interval_seconds: How often to check for tasks (default: 60s)
        """
        self.check_interval_seconds = check_interval_seconds
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start the warehouse scheduler thread."""
        if self._running:
            logger.warning("Warehouse scheduler already running")
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(
            f"Warehouse scheduler started (check interval: {self.check_interval_seconds}s)"
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the warehouse scheduler thread.

        Args:
            timeout: Max seconds to wait for thread to stop
        """
        if not self._running:
            return

        logger.info("Stopping warehouse scheduler...")
        self._running = False
        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning("Warehouse scheduler thread did not stop cleanly")
            else:
                logger.info("Warehouse scheduler stopped")

        self._thread = None

    def _run_loop(self) -> None:
        """Main scheduler loop - checks for tasks periodically."""
        logger.info("Warehouse scheduler loop started")

        while self._running and not self._stop_event.is_set():
            try:
                self._check_all_catalogs()
            except Exception as e:
                logger.error(f"Error in warehouse scheduler loop: {e}", exc_info=True)

            # Wait for next interval (with interrupt support)
            self._stop_event.wait(self.check_interval_seconds)

        logger.info("Warehouse scheduler loop exited")

    def _check_all_catalogs(self) -> None:
        """Check all catalogs for warehouse tasks that need to run."""
        try:
            with get_db_context() as db:
                # Get all active catalogs
                catalogs = db.query(Catalog).all()

                for catalog in catalogs:
                    try:
                        self._check_catalog(str(catalog.id))
                    except Exception as e:
                        logger.error(
                            f"Error checking catalog {catalog.id}: {e}", exc_info=True
                        )

        except Exception as e:
            logger.error(f"Error getting catalogs: {e}", exc_info=True)

    def _check_catalog(self, catalog_id: str) -> None:
        """Check a single catalog for tasks that need to run.

        Args:
            catalog_id: Catalog ID to check
        """
        try:
            with get_db_context() as db:
                # Get warehouse config for this catalog
                configs = (
                    db.query(WarehouseConfig)
                    .filter(
                        WarehouseConfig.catalog_id == catalog_id,
                        WarehouseConfig.enabled == True,  # noqa: E712
                    )
                    .all()
                )

                now = datetime.utcnow()

                for config in configs:
                    # Check if it's time to run this task
                    if config.next_run and config.next_run > now:
                        continue

                    # Initialize defaults if not set
                    if not config.threshold:
                        task = WAREHOUSE_TASKS.get(config.task_type)
                        if task:
                            config.threshold = task.default_threshold

                    # Assess if task needs to run
                    should_run, count, job_params = assess_task_need(
                        config.task_type, catalog_id, config.threshold
                    )

                    # Update last_run and next_run
                    config.last_run = now
                    config.next_run = now + timedelta(
                        minutes=config.check_interval_minutes
                    )

                    if should_run:
                        self._submit_warehouse_job(
                            catalog_id=catalog_id,
                            task_type=config.task_type,
                            job_params=job_params,
                            trigger_reason=f"{config.task_type}: {count} items need processing",
                        )

                db.commit()

        except Exception as e:
            logger.error(
                f"Error checking catalog {catalog_id} tasks: {e}", exc_info=True
            )

    def _submit_warehouse_job(
        self,
        catalog_id: str,
        task_type: str,
        job_params: Dict,
        trigger_reason: str,
    ) -> None:
        """Submit a warehouse job.

        Args:
            catalog_id: Catalog ID
            task_type: Warehouse task type
            job_params: Job parameters
            trigger_reason: Why this job was triggered
        """
        task = WAREHOUSE_TASKS.get(task_type)
        if not task:
            logger.error(f"Unknown warehouse task type: {task_type}")
            return

        job_type = task.job_type
        if job_type not in JOB_FUNCTIONS:
            logger.error(f"Unknown job type: {job_type}")
            return

        # Skip if there's already an active job of this type for this catalog
        if has_active_job(catalog_id, job_type):
            logger.info(
                f"Skipping warehouse job {job_type} for catalog {catalog_id}: "
                "active job already exists"
            )
            return

        try:
            with get_db_context() as db:
                # Create warehouse job with lower priority
                job = create_job(
                    db,
                    job_type=job_type,
                    catalog_id=catalog_id,
                    parameters=job_params,
                    job_source="warehouse",
                    priority=task.priority,
                    warehouse_trigger=trigger_reason,
                )

                logger.info(
                    f"Submitted warehouse job {job.id}: {job_type} (trigger: {trigger_reason})"
                )

                # Run in background
                job_func = JOB_FUNCTIONS[job_type]
                run_job_in_background(
                    job_id=job.id,
                    catalog_id=catalog_id,
                    func=job_func,
                    parameters=job_params,
                )

        except Exception as e:
            logger.error(f"Error submitting warehouse job: {e}", exc_info=True)

    def initialize_warehouse_config(self, catalog_id: str) -> None:
        """Initialize warehouse config for a catalog with default settings.

        Args:
            catalog_id: Catalog ID
        """
        try:
            with get_db_context() as db:
                # Check if config already exists
                existing = (
                    db.query(WarehouseConfig)
                    .filter(WarehouseConfig.catalog_id == catalog_id)
                    .count()
                )

                if existing > 0:
                    logger.info(
                        f"Warehouse config already exists for catalog {catalog_id}"
                    )
                    return

                # Create default config for each task
                now = datetime.utcnow()
                for task_type, task in WAREHOUSE_TASKS.items():
                    config = WarehouseConfig(
                        catalog_id=catalog_id,
                        task_type=task_type,
                        enabled=False,  # Start disabled by default
                        check_interval_minutes=task.default_interval_minutes,
                        threshold=task.default_threshold,
                        last_run=None,
                        next_run=now,
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(config)

                db.commit()
                logger.info(
                    f"Initialized warehouse config for catalog {catalog_id} with {len(WAREHOUSE_TASKS)} tasks"
                )

        except Exception as e:
            logger.error(
                f"Error initializing warehouse config for {catalog_id}: {e}",
                exc_info=True,
            )


# Global scheduler instance
_scheduler: Optional[WarehouseScheduler] = None


def get_scheduler() -> WarehouseScheduler:
    """Get or create the global warehouse scheduler instance.

    Returns:
        Global WarehouseScheduler instance
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = WarehouseScheduler()
    return _scheduler


def start_warehouse_scheduler() -> None:
    """Start the global warehouse scheduler."""
    scheduler = get_scheduler()
    scheduler.start()


def stop_warehouse_scheduler(timeout: float = 5.0) -> None:
    """Stop the global warehouse scheduler.

    Args:
        timeout: Max seconds to wait for shutdown
    """
    global _scheduler
    if _scheduler:
        _scheduler.stop(timeout=timeout)
        _scheduler = None
