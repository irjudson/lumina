"""Warehouse automation API endpoints."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db import get_db
from ...db.models import Catalog, WarehouseConfig
from ...jobs.warehouse_scheduler import get_scheduler
from ...jobs.warehouse_tasks import WAREHOUSE_TASKS

logger = logging.getLogger(__name__)

router = APIRouter()


class WarehouseTaskConfigRequest(BaseModel):
    """Request to update warehouse task configuration."""

    enabled: bool
    check_interval_minutes: int
    threshold: Dict[str, Any]


class WarehouseTaskConfigResponse(BaseModel):
    """Response with warehouse task configuration."""

    task_type: str
    enabled: bool
    check_interval_minutes: int
    threshold: Dict[str, Any]
    last_run: Optional[str] = None
    next_run: Optional[str] = None


class WarehouseConfigResponse(BaseModel):
    """Response with all warehouse configurations for a catalog."""

    catalog_id: str
    tasks: List[WarehouseTaskConfigResponse]


class WarehouseStatusResponse(BaseModel):
    """Response with warehouse scheduler status."""

    scheduler_running: bool
    available_tasks: List[str]
    catalog_tasks: List[WarehouseTaskConfigResponse]


@router.get(
    "/catalogs/{catalog_id}/warehouse/config", response_model=WarehouseConfigResponse
)
def get_warehouse_config(catalog_id: str, db: Session = Depends(get_db)):
    """Get warehouse automation config for a catalog.

    Args:
        catalog_id: Catalog ID
        db: Database session

    Returns:
        Warehouse configuration
    """
    # Verify catalog exists
    catalog = db.query(Catalog).filter(Catalog.id == catalog_id).first()
    if not catalog:
        raise HTTPException(status_code=404, detail="Catalog not found")

    # Get warehouse config
    configs = (
        db.query(WarehouseConfig).filter(WarehouseConfig.catalog_id == catalog_id).all()
    )

    # If no config exists, initialize it
    if not configs:
        scheduler = get_scheduler()
        scheduler.initialize_warehouse_config(catalog_id)
        configs = (
            db.query(WarehouseConfig)
            .filter(WarehouseConfig.catalog_id == catalog_id)
            .all()
        )

    return WarehouseConfigResponse(
        catalog_id=catalog_id,
        tasks=[
            WarehouseTaskConfigResponse(
                task_type=config.task_type,
                enabled=config.enabled,
                check_interval_minutes=config.check_interval_minutes,
                threshold=config.threshold or {},
                last_run=config.last_run.isoformat() if config.last_run else None,
                next_run=config.next_run.isoformat() if config.next_run else None,
            )
            for config in configs
        ],
    )


@router.put(
    "/catalogs/{catalog_id}/warehouse/config/{task_type}",
    response_model=WarehouseTaskConfigResponse,
)
def update_warehouse_task_config(
    catalog_id: str,
    task_type: str,
    request: WarehouseTaskConfigRequest,
    db: Session = Depends(get_db),
):
    """Update warehouse task configuration.

    Args:
        catalog_id: Catalog ID
        task_type: Task type identifier
        request: Updated configuration
        db: Database session

    Returns:
        Updated configuration
    """
    # Verify catalog exists
    catalog = db.query(Catalog).filter(Catalog.id == catalog_id).first()
    if not catalog:
        raise HTTPException(status_code=404, detail="Catalog not found")

    # Verify task type is valid
    if task_type not in WAREHOUSE_TASKS:
        raise HTTPException(status_code=400, detail=f"Unknown task type: {task_type}")

    # Get or create config
    config = (
        db.query(WarehouseConfig)
        .filter(
            WarehouseConfig.catalog_id == catalog_id,
            WarehouseConfig.task_type == task_type,
        )
        .first()
    )

    if not config:
        # Create new config
        config = WarehouseConfig(
            catalog_id=catalog_id,
            task_type=task_type,
            enabled=request.enabled,
            check_interval_minutes=request.check_interval_minutes,
            threshold=request.threshold,
            created_at=datetime.utcnow(),
        )
        db.add(config)
    else:
        # Update existing config
        config.enabled = request.enabled
        config.check_interval_minutes = request.check_interval_minutes
        config.threshold = request.threshold
        config.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(config)

    return WarehouseTaskConfigResponse(
        task_type=config.task_type,
        enabled=config.enabled,
        check_interval_minutes=config.check_interval_minutes,
        threshold=config.threshold or {},
        last_run=config.last_run.isoformat() if config.last_run else None,
        next_run=config.next_run.isoformat() if config.next_run else None,
    )


@router.get(
    "/catalogs/{catalog_id}/warehouse/status", response_model=WarehouseStatusResponse
)
def get_warehouse_status(catalog_id: str, db: Session = Depends(get_db)):
    """Get warehouse automation status for a catalog.

    Args:
        catalog_id: Catalog ID
        db: Database session

    Returns:
        Warehouse status
    """
    # Verify catalog exists
    catalog = db.query(Catalog).filter(Catalog.id == catalog_id).first()
    if not catalog:
        raise HTTPException(status_code=404, detail="Catalog not found")

    # Get scheduler status
    scheduler = get_scheduler()
    scheduler_running = scheduler._running if scheduler else False

    # Get catalog tasks
    configs = (
        db.query(WarehouseConfig).filter(WarehouseConfig.catalog_id == catalog_id).all()
    )

    return WarehouseStatusResponse(
        scheduler_running=scheduler_running,
        available_tasks=list(WAREHOUSE_TASKS.keys()),
        catalog_tasks=[
            WarehouseTaskConfigResponse(
                task_type=config.task_type,
                enabled=config.enabled,
                check_interval_minutes=config.check_interval_minutes,
                threshold=config.threshold or {},
                last_run=config.last_run.isoformat() if config.last_run else None,
                next_run=config.next_run.isoformat() if config.next_run else None,
            )
            for config in configs
        ],
    )


@router.post("/scheduler/start")
def start_scheduler():
    """Start the warehouse scheduler."""
    try:
        scheduler = get_scheduler()
        scheduler.start()
        return {"message": "Warehouse scheduler started", "running": True}
    except Exception as e:
        logger.error(f"Failed to start warehouse scheduler: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to start scheduler: {str(e)}"
        )


@router.post("/scheduler/stop")
def stop_scheduler():
    """Stop the warehouse scheduler."""
    try:
        scheduler = get_scheduler()
        scheduler.stop()
        return {"message": "Warehouse scheduler stopped", "running": False}
    except Exception as e:
        logger.error(f"Failed to stop warehouse scheduler: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to stop scheduler: {str(e)}"
        )


@router.get("/scheduler/status")
def get_scheduler_status():
    """Get warehouse scheduler status."""
    scheduler = get_scheduler()
    return {
        "running": scheduler._running if scheduler else False,
        "check_interval_seconds": (
            scheduler.check_interval_seconds if scheduler else None
        ),
    }
