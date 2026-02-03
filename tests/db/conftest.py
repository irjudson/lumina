"""Test database configuration and fixtures.

This module sets up the test database with proper schema and fixtures.
"""

import os
import uuid
from datetime import datetime
from typing import Generator

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

# Test database URL - separate from production
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://pg:buffalo-jump@localhost:5432/lumina_test",
)


@pytest.fixture(scope="session")
def db_engine():  # type: ignore[no-untyped-def]
    """Create test database engine and initialize schema.

    This fixture runs once per test session and:
    1. Creates all SQLModel tables
    2. Sets up extensions (pgvector)
    """
    engine = create_engine(TEST_DATABASE_URL, echo=False)

    # Ensure pgvector extension exists
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    # Create all tables
    SQLModel.metadata.create_all(engine)

    yield engine

    # Don't drop tables - preserve schema for debugging


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:  # type: ignore[no-untyped-def]
    """Create a database session with automatic rollback.

    Each test gets a fresh session that rolls back after completion,
    keeping tests isolated without losing schema.
    """
    with Session(db_engine) as session:
        yield session
        session.rollback()


@pytest.fixture
def clean_images_table(db_session: Session) -> None:
    """Clean the images table before a test."""
    db_session.exec(text("DELETE FROM images"))  # type: ignore[call-overload]
    db_session.commit()


@pytest.fixture
def test_catalog_id(db_session: Session) -> uuid.UUID:
    """Create a test catalog and return its ID.

    The catalog is created fresh for each test to ensure isolation.
    """
    from lumina.models.catalog import Catalog

    catalog_id = uuid.uuid4()
    catalog = Catalog(
        id=catalog_id,
        name=f"Test Catalog {catalog_id.hex[:8]}",
        schema_name=f"test_catalog_{catalog_id.hex[:8]}",
        source_directories=["/test/photos"],
    )
    db_session.add(catalog)
    db_session.commit()

    return catalog_id


@pytest.fixture
def sample_image_data(test_catalog_id: uuid.UUID) -> list[dict]:
    """Provide sample image data for testing.

    Returns a list of image dictionaries with known values
    for predictable test outcomes.
    """
    from lumina.models.image import FileType

    base_time = datetime(2024, 1, 15, 12, 0, 0)

    return [
        {
            "id": f"test-img-001-{test_catalog_id.hex[:8]}",
            "catalog_id": test_catalog_id,
            "source_path": "/photos/2024/01/IMG_001.jpg",
            "file_type": FileType.image,
            "checksum": "sha256:abc123def456",
            "size_bytes": 2500000,
            "dhash": "0123456789abcdef",
            "ahash": "fedcba9876543210",
            "whash": "1111222233334444",
            "quality_score": 85,
            "dates": {
                "selected_date": base_time.isoformat(),
                "exif_date": base_time.isoformat(),
            },
            "metadata_json": {
                "camera_make": "Canon",
                "camera_model": "EOS R5",
                "iso": 400,
                "aperture": 2.8,
            },
        },
        {
            "id": f"test-img-002-{test_catalog_id.hex[:8]}",
            "catalog_id": test_catalog_id,
            "source_path": "/photos/2024/01/IMG_002.jpg",
            "file_type": FileType.image,
            "checksum": "sha256:def789ghi012",
            "size_bytes": 3200000,
            "dhash": "0123456789abcdef",  # Same hash = duplicate
            "ahash": "fedcba9876543211",
            "whash": "1111222233334445",
            "quality_score": 92,
            "dates": {
                "selected_date": (base_time).isoformat(),
            },
            "metadata_json": {
                "camera_make": "Canon",
                "camera_model": "EOS R5",
            },
        },
        {
            "id": f"test-img-003-{test_catalog_id.hex[:8]}",
            "catalog_id": test_catalog_id,
            "source_path": "/photos/2024/01/IMG_003.jpg",
            "file_type": FileType.image,
            "checksum": "sha256:unique123456",
            "size_bytes": 1800000,
            "dhash": None,  # No hash computed yet
            "ahash": None,
            "whash": None,
            "quality_score": 78,
            "dates": {},
            "metadata_json": {},
        },
    ]
