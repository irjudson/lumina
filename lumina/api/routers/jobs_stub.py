"""Minimal jobs router stub during Celery migration."""

import logging
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()

# Stub functions for tests
def _safe_get_task_state(task: Any) -> str:
    """Stub."""
    return "PENDING"

def _safe_get_task_info(task: Any) -> Any:
    """Stub."""
    return {}

