"""
Generic Parallel Job Framework.

This module provides a unified framework for defining and managing parallel
jobs that follow a common pattern:
1. Discover work items for a catalog
2. Process items in parallel batches
3. Optionally finalize/aggregate results

The framework replaces multiple similar parallel_*.py implementations with
a single, configurable job definition system.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

logger = logging.getLogger(__name__)

# Type variable for work items (e.g., image paths, image IDs, etc.)
T = TypeVar("T")


@dataclass
class ParallelJob(Generic[T]):
    """
    Definition of a parallel processing job.

    A ParallelJob captures all the configuration needed to run a parallel
    job across a catalog, including discovery, processing, and finalization.

    Type Parameters:
        T: The type of work items (e.g., str for image paths, tuple for pairs)

    Attributes:
        name: Unique identifier for this job type
        discover: Function that finds work items for a catalog
        process: Function that processes a single work item
        finalize: Optional function to aggregate results after all processing
        batch_size: Number of items per batch (default: 1000)
        max_workers: Maximum parallel workers (default: 4)
        retry_on_failure: Whether to retry failed items (default: True)
        max_retries: Maximum retry attempts per item (default: 3)
        timeout_seconds: Optional timeout per item in seconds
    """

    name: str
    discover: Callable[[str], List[T]]
    process: Callable[..., Dict[str, Any]]
    finalize: Optional[Callable[..., Dict[str, Any]]] = None
    batch_size: int = 1000
    max_workers: int = 4
    retry_on_failure: bool = True
    max_retries: int = 3
    timeout_seconds: Optional[int] = None


class JobRegistry:
    """
    Registry for parallel job definitions.

    Provides a central place to register and retrieve job definitions
    by name, enabling dynamic job execution based on configuration.
    """

    def __init__(self) -> None:
        """Initialize an empty job registry."""
        self._jobs: Dict[str, ParallelJob] = {}

    def register(self, job: ParallelJob) -> None:
        """
        Register a job definition.

        Args:
            job: The ParallelJob to register

        Raises:
            ValueError: If a job with the same name is already registered
        """
        if job.name in self._jobs:
            raise ValueError(f"Job '{job.name}' is already registered")
        self._jobs[job.name] = job

    def get(self, name: str) -> Optional[ParallelJob]:
        """
        Retrieve a job by name.

        Args:
            name: The job name to look up

        Returns:
            The ParallelJob if found, None otherwise
        """
        return self._jobs.get(name)

    def list_jobs(self) -> List[str]:
        """
        List all registered job names.

        Returns:
            List of registered job names
        """
        return list(self._jobs.keys())


# Global registry instance
REGISTRY = JobRegistry()


def register_job(job: ParallelJob) -> ParallelJob:
    """
    Register a job in the global registry.

    This function can be used as a decorator or called directly
    to add jobs to the global REGISTRY.

    Args:
        job: The ParallelJob to register

    Returns:
        The same job (allows use as decorator)

    Example:
        # Direct registration
        register_job(my_job)

        # Or create and register inline
        job = register_job(ParallelJob(
            name="scan",
            discover=discover_images,
            process=process_image,
        ))
    """
    REGISTRY.register(job)
    return job


class JobExecutor(Generic[T]):
    """
    Executor for parallel jobs.

    JobExecutor manages the execution lifecycle of a ParallelJob:
    1. Discovery - find work items for a catalog
    2. Batching - split items into batches
    3. Processing - execute batches in parallel
    4. Finalization - aggregate results

    Type Parameters:
        T: The type of work items handled by the job
    """

    def __init__(self, job: ParallelJob[T]) -> None:
        """
        Initialize a job executor.

        Args:
            job: The ParallelJob definition to execute
        """
        self.job = job

    def run(self, job_id: str, catalog_id: str, **kwargs: Any) -> Dict[str, Any]:
        """
        Execute the job for a catalog.

        Runs the full job lifecycle: discover -> process -> finalize.

        Args:
            job_id: Unique identifier for this job execution
            catalog_id: The catalog to process
            **kwargs: Additional arguments passed to process function

        Returns:
            Dict containing:
                - success_count: Number of successfully processed items
                - error_count: Number of failed items
                - total_items: Total items discovered
                - errors: List of error details
                - Plus any keys returned by finalize()
        """
        logger.info(
            f"Starting job {self.job.name} (id={job_id}) for catalog {catalog_id}"
        )

        # Phase 1: Discovery
        items = self.job.discover(catalog_id)
        total_items = len(items)
        logger.info(f"Discovered {total_items} items for job {job_id}")

        if not items:
            return self._empty_result()

        # Phase 2: Create batches
        batches = self._create_batches(items)
        logger.info(f"Created {len(batches)} batches for job {job_id}")

        # Phase 3: Process in parallel
        all_results: List[Dict[str, Any]] = []
        all_errors: List[Dict[str, Any]] = []
        success_count = 0
        error_count = 0

        with ThreadPoolExecutor(max_workers=self.job.max_workers) as executor:
            futures = {
                executor.submit(self._process_batch, batch, catalog_id, kwargs): i
                for i, batch in enumerate(batches)
            }

            for future in as_completed(futures):
                batch_result = future.result()
                all_results.extend(batch_result["results"])
                all_errors.extend(batch_result["errors"])
                success_count += batch_result["success_count"]
                error_count += batch_result["error_count"]

        # Phase 4: Finalize
        result = {
            "success_count": success_count,
            "error_count": error_count,
            "total_items": total_items,
            "errors": all_errors,
        }

        if self.job.finalize is not None:
            finalize_result = self.job.finalize(all_results, catalog_id)
            result.update(finalize_result)

        logger.info(
            f"Job {job_id} completed: {success_count} succeeded, {error_count} failed"
        )
        return result

    def _create_batches(self, items: List[T]) -> List[List[T]]:
        """
        Split items into batches.

        Args:
            items: List of work items

        Returns:
            List of batches, each containing up to batch_size items
        """
        batch_size = self.job.batch_size
        return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]

    def _process_batch(
        self, batch: List[T], catalog_id: str, kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process a single batch of items.

        Args:
            batch: List of items to process
            catalog_id: The catalog being processed
            kwargs: Additional arguments for process function

        Returns:
            Dict with results, errors, success_count, error_count
        """
        results: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        success_count = 0
        error_count = 0

        for item in batch:
            try:
                result = self.job.process(item, catalog_id=catalog_id, **kwargs)
                results.append(result)
                success_count += 1
            except Exception as e:
                logger.warning(f"Error processing item {item}: {e}")
                errors.append({"item": item, "error": str(e)})
                error_count += 1

        return {
            "results": results,
            "errors": errors,
            "success_count": success_count,
            "error_count": error_count,
        }

    def _empty_result(self) -> Dict[str, Any]:
        """
        Return an empty result dict.

        Returns:
            Dict with zero counts and empty lists
        """
        return {
            "success_count": 0,
            "error_count": 0,
            "total_items": 0,
            "errors": [],
        }


class JobExecutorWithDB(JobExecutor[T]):
    """
    JobExecutor with database-backed batch tracking.

    Extends JobExecutor to:
    - Create JobBatch records for restartability
    - Track progress in database
    - Support cancellation
    - Publish progress events
    """

    def __init__(self, job: ParallelJob[T], db_session_factory: Callable) -> None:
        """
        Initialize a job executor with database support.

        Args:
            job: The ParallelJob definition to execute
            db_session_factory: Factory function that returns database sessions
        """
        super().__init__(job)
        self.db_session_factory = db_session_factory

    def run(
        self,
        job_id: str,
        catalog_id: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Execute with database tracking.

        For now, delegates to parent implementation.
        Full implementation will use BatchManager pattern.

        Args:
            job_id: Unique identifier for this job execution
            catalog_id: The catalog to process
            **kwargs: Additional arguments passed to process function

        Returns:
            Dict containing execution results (see parent class)
        """
        # For now, delegate to parent
        # Full implementation will use BatchManager pattern
        return super().run(job_id, catalog_id, **kwargs)
