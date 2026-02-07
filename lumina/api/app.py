"""FastAPI application factory."""

import logging
from pathlib import Path
from typing import Union

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from ..db import get_db, init_db
from ..db.models import Catalog
from .routers import catalogs, images
from .routers import jobs_new as jobs

logger = logging.getLogger(__name__)


def ensure_default_catalog() -> None:
    """Create a default catalog if none exist."""
    try:
        with next(get_db()) as db:
            # Check if any catalogs exist
            catalog_count = db.query(Catalog).count()

            if catalog_count == 0:
                logger.info("No catalogs found, creating default catalog...")

                # Collect ALL existing photo directories
                source_dirs = []

                # Docker-mounted host directories (from docker-compose.yml)
                docker_mounts = [
                    Path("/host/home"),  # User home directories
                    Path("/host/synology"),  # Synology NAS
                ]

                # Check Docker mounts for common photo locations
                for mount_root in docker_mounts:
                    if not mount_root.exists():
                        continue

                    try:
                        # For /host/home, check each user's photo directories
                        if mount_root.name == "home":
                            for user_dir in mount_root.iterdir():
                                if user_dir.is_dir():
                                    for photo_subdir in ["Pictures", "Photos", "DCIM"]:
                                        photo_path = user_dir / photo_subdir
                                        if photo_path.exists() and photo_path.is_dir():
                                            source_dirs.append(str(photo_path))
                                            logger.info(
                                                f"Found photo directory: {photo_path}"
                                            )

                        # For NAS/network drives, add root if it exists
                        elif mount_root.exists() and mount_root.is_dir():
                            source_dirs.append(str(mount_root))
                            logger.info(f"Found network storage: {mount_root}")

                    except Exception as e:
                        logger.debug(f"Error scanning {mount_root}: {e}")
                        continue

                # Standard Docker mount points
                standard_mounts = [
                    Path("/photos"),
                    Path("/app/photos"),
                ]

                for dir_path in standard_mounts:
                    try:
                        if dir_path.exists() and dir_path.is_dir():
                            source_dirs.append(str(dir_path))
                            logger.info(f"Found photo directory: {dir_path}")
                    except Exception:
                        continue

                # Device mount points (iPhone, Android, USB drives)
                device_mount_roots = [
                    Path("/media"),
                    Path("/run/media"),
                    Path("/mnt"),
                    Path("/Volumes"),  # macOS
                ]

                for mount_root in device_mount_roots:
                    try:
                        if mount_root.exists():
                            for device_dir in mount_root.iterdir():
                                if not device_dir.is_dir():
                                    continue

                                # Look for DCIM (phones/cameras)
                                dcim_path = device_dir / "DCIM"
                                if dcim_path.exists() and dcim_path.is_dir():
                                    source_dirs.append(str(dcim_path))
                                    logger.info(f"Found device DCIM: {dcim_path}")
                                # iPhone/iOS backup folders
                                elif (
                                    "iPhone" in device_dir.name
                                    or "iOS" in device_dir.name
                                ):
                                    source_dirs.append(str(device_dir))
                                    logger.info(f"Found iOS device: {device_dir}")

                    except Exception as e:
                        logger.debug(
                            f"Error scanning device mounts in {mount_root}: {e}"
                        )
                        continue

                # If no directories found, create ~/Pictures as fallback
                if not source_dirs:
                    pictures_dir = Path.home() / "Pictures"
                    pictures_dir.mkdir(parents=True, exist_ok=True)
                    source_dirs = [str(pictures_dir)]
                    logger.info(f"Created default directory: {pictures_dir}")

                # Create default catalog
                import uuid

                catalog_id = uuid.uuid4()
                default_catalog = Catalog(
                    id=catalog_id,
                    name="My Photos",
                    schema_name=f"deprecated_{catalog_id}",
                    source_directories=source_dirs,
                    organized_directory=None,
                )

                db.add(default_catalog)
                db.commit()

                logger.info(
                    f"Created default catalog 'My Photos' with {len(source_dirs)} source directories: {', '.join(source_dirs)}"
                )
            else:
                logger.info(f"Found {catalog_count} existing catalog(s)")

    except Exception as e:
        logger.error(f"Failed to ensure default catalog: {e}")
        # Don't fail startup if catalog creation fails


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Lumina API",
        description="Lumina - Visual Asset Management - Photo/Video Catalog API",
        version="2.0.0",
    )

    # CORS middleware (allow all origins for local development)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Initialize database on startup
    @app.on_event("startup")
    async def startup_event() -> None:
        logger.info("Starting Lumina API...")
        init_db()
        logger.info("Database initialized")

        # Ensure default catalog exists
        ensure_default_catalog()

    # Graceful shutdown
    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        logger.info("Shutting down Lumina API...")
        # Give WebSocket connections a moment to close gracefully
        import asyncio

        await asyncio.sleep(0.5)
        logger.info("Shutdown complete")

    # Include routers
    app.include_router(catalogs.router, prefix="/api/catalogs", tags=["catalogs"])
    app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
    app.include_router(images.router, prefix="/api", tags=["images"])

    # Health check endpoint
    @app.get("/health")
    async def health_check() -> dict[str, str]:
        return {"status": "healthy"}

    # Serve static files and root endpoint
    static_dir = Path(__file__).parent.parent / "web" / "static"
    if static_dir.exists():
        logger.info(f"Mounting static files from: {static_dir}")

        # Mount assets directory for proper MIME types
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            logger.info(f"Mounting assets from: {assets_dir}")
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        # Serve index.html for SPA routes (Vue Router)
        from fastapi.responses import FileResponse, HTMLResponse

        @app.get("/")
        async def serve_root() -> FileResponse:
            """Serve index.html for root path."""
            return FileResponse(static_dir / "index.html")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str) -> Union[FileResponse, HTMLResponse]:
            """Serve index.html for all non-API, non-asset routes (SPA support)."""
            # Check if file exists in static dir
            file_path = static_dir / full_path
            if file_path.is_file():
                return FileResponse(file_path)

            # Otherwise serve index.html for SPA routing
            index_path = static_dir / "index.html"
            if index_path.exists():
                return FileResponse(index_path, media_type="text/html")
            else:
                return HTMLResponse("<h1>Frontend not built</h1>", status_code=500)

    else:
        # Fallback: redirect to docs if no static files
        @app.get("/")
        async def redirect_to_docs() -> RedirectResponse:
            return RedirectResponse(url="/docs")

    return app


# Create app instance for uvicorn
app = create_app()
