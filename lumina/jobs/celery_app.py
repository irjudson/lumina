"""
Celery app stub - provides no-op decorators when Celery is not available.

The Lumina codebase has migrated from Celery to a threading-based job system.
This module maintains backward compatibility with existing task decorators
by providing a DummyApp that makes @app.task decorators pass-through.

Note: The files using these decorators (reorganize.py, job_recovery.py,
serial_descriptions.py) are legacy code that should eventually be migrated
to the new threading-based job_implementations.py pattern.
"""

from typing import Any, Callable, Dict

try:
    from celery import Celery

    # If Celery is available, create a real app
    app = Celery("lumina")
    app.config_from_object("lumina.jobs.celery_config", silent=True)
    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False

    class DummyApp:
        """No-op Celery app for when Celery isn't installed."""

        @staticmethod
        def task(*args: Any, **kwargs: Any) -> Callable[..., Any]:
            """No-op decorator that returns the function unchanged."""

            def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
                return func

            # Handle both @app.task and @app.task() syntax
            if len(args) == 1 and callable(args[0]):
                return args[0]
            return decorator

        @property
        def tasks(self) -> Dict[str, Any]:
            """Return empty dict for task registry lookups."""
            return {}

    app = DummyApp()  # type: ignore
