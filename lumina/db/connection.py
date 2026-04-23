"""Database connection and session management."""

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

logger = logging.getLogger(__name__)

# Create SQLAlchemy engine
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # Verify connections before using
    pool_size=10,  # Connection pool size
    max_overflow=20,  # Allow up to 20 additional connections
    echo=settings.sql_echo,  # Log SQL queries (debug mode)
    connect_args={"client_encoding": "utf8"},  # Force UTF-8 encoding
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _populate_reference_tables(db: Session) -> None:
    """Populate reference tables with required data."""
    from .models import ImageStatus

    # Check if ImageStatus table needs population
    if db.query(ImageStatus).count() == 0:
        logger.info("Populating image_statuses reference table...")
        statuses = [
            ImageStatus(id="active", name="Active", description="Normal visible image"),
            ImageStatus(
                id="rejected",
                name="Rejected",
                description="Rejected from burst/duplicate review",
            ),
            ImageStatus(
                id="archived", name="Archived", description="Manually archived by user"
            ),
            ImageStatus(
                id="flagged",
                name="Flagged",
                description="Flagged for review or special attention",
            ),
        ]
        db.add_all(statuses)
        db.commit()
        logger.info(f"Added {len(statuses)} image status records")
    else:
        logger.debug(
            f"ImageStatus table already populated ({db.query(ImageStatus).count()} records)"
        )


def init_db() -> None:
    """Initialize database by creating all tables and populating reference data."""
    logger.info("Initializing database...")

    # Create all tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")

    # Run dedup schema migration (idempotent — safe to call every startup)
    from .migrations.dedup_schema import upgrade

    upgrade(engine)
    logger.info("Dedup schema migration applied")

    # Run organized_path migration (idempotent)
    from .migrations.organized_path import upgrade as upgrade_organized_path

    upgrade_organized_path(engine)
    logger.info("Organized path migration applied")

    # Run content_class migration (idempotent)
    from .migrations.content_class import upgrade as upgrade_content_class

    upgrade_content_class(engine)
    logger.info("Content class migration applied")

    # Run events schema migration (idempotent)
    from .migrations.events_schema import upgrade as upgrade_events

    upgrade_events(engine)
    logger.info("Events schema migration applied")

    # Populate reference tables
    db = SessionLocal()
    try:
        _populate_reference_tables(db)
    finally:
        db.close()

    logger.info("Database initialized successfully")


def get_db() -> Generator[Session, None, None]:
    """
    Get database session for FastAPI dependency injection.

    Usage in FastAPI:
        @app.get("/items")
        def read_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """
    Get database session for use in context manager.

    Usage:
        with get_db_context() as db:
            catalog = db.query(Catalog).first()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
