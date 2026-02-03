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

from dataclasses import dataclass
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

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
