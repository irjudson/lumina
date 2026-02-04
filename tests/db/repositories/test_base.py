"""Tests for base repository pattern."""

import uuid
from typing import Optional

import pytest
from sqlalchemy import text
from sqlmodel import Field, Session, SQLModel

# Mark all tests in this module as integration tests (require database)
pytestmark = pytest.mark.integration


# Model for repository tests - registered with SQLModel's metadata
# The table is created by conftest.py's SQLModel.metadata.create_all()
class MockEntity(SQLModel, table=True):
    """Mock entity for repository testing."""

    __tablename__ = "test_base_mock_entities"

    id: str = Field(primary_key=True)
    name: str = Field(max_length=100)
    value: Optional[int] = Field(default=None)


@pytest.fixture(scope="module")
def mock_table_created(engine):  # type: ignore[no-untyped-def]
    """Create the mock entity table for testing."""
    SQLModel.metadata.create_all(engine, tables=[MockEntity.__table__])  # type: ignore[attr-defined]
    yield
    SQLModel.metadata.drop_all(engine, tables=[MockEntity.__table__])  # type: ignore[attr-defined]


@pytest.fixture
def session(engine, mock_table_created):  # type: ignore[no-untyped-def]
    """Create database session with cleanup."""
    with Session(engine) as db_session:
        # Clean up any existing test data before each test
        db_session.exec(text("DELETE FROM test_base_mock_entities"))  # type: ignore[call-overload]
        db_session.commit()
        yield db_session
        db_session.rollback()


def test_repository_add(session: Session) -> None:
    """Should add entity to database."""
    from lumina.db.repositories.base import BaseRepository

    repo = BaseRepository(session, MockEntity)
    entity = MockEntity(id=f"add-{uuid.uuid4().hex[:8]}", name="Test")

    result = repo.add(entity)
    repo.commit()

    assert result.name == "Test"


def test_repository_get(session: Session) -> None:
    """Should retrieve entity by ID."""
    from lumina.db.repositories.base import BaseRepository

    repo = BaseRepository(session, MockEntity)
    test_id = f"get-{uuid.uuid4().hex[:8]}"
    entity = MockEntity(id=test_id, name="Test")
    repo.add(entity)
    repo.commit()

    result = repo.get(test_id)

    assert result is not None
    assert result.id == test_id
    assert result.name == "Test"


def test_repository_get_not_found(session: Session) -> None:
    """Should return None for non-existent ID."""
    from lumina.db.repositories.base import BaseRepository

    repo = BaseRepository(session, MockEntity)

    result = repo.get("nonexistent")

    assert result is None


def test_repository_list(session: Session) -> None:
    """Should list entities with pagination."""
    from lumina.db.repositories.base import BaseRepository

    repo = BaseRepository(session, MockEntity)
    for i in range(5):
        repo.add(MockEntity(id=f"list-{uuid.uuid4().hex[:8]}-{i}", name=f"Test {i}"))
    repo.commit()

    # Get first page
    result = repo.list(limit=2, offset=0)
    assert len(result) == 2

    # Get second page
    result = repo.list(limit=2, offset=2)
    assert len(result) == 2

    # Get last page
    result = repo.list(limit=2, offset=4)
    assert len(result) == 1


def test_repository_update(session: Session) -> None:
    """Should update existing entity."""
    from lumina.db.repositories.base import BaseRepository

    repo = BaseRepository(session, MockEntity)
    test_id = f"update-{uuid.uuid4().hex[:8]}"
    entity = MockEntity(id=test_id, name="Original")
    repo.add(entity)
    repo.commit()

    # Update
    entity.name = "Updated"
    repo.update(entity)
    repo.commit()

    result = repo.get(test_id)
    assert result is not None
    assert result.name == "Updated"


def test_repository_delete(session: Session) -> None:
    """Should delete entity."""
    from lumina.db.repositories.base import BaseRepository

    repo = BaseRepository(session, MockEntity)
    test_id = f"delete-{uuid.uuid4().hex[:8]}"
    entity = MockEntity(id=test_id, name="Test")
    repo.add(entity)
    repo.commit()

    repo.delete(entity)
    repo.commit()

    result = repo.get(test_id)
    assert result is None


def test_repository_rollback(session: Session) -> None:
    """Should rollback uncommitted changes."""
    from lumina.db.repositories.base import BaseRepository

    repo = BaseRepository(session, MockEntity)
    test_id = f"rollback-{uuid.uuid4().hex[:8]}"
    entity = MockEntity(id=test_id, name="Test")
    repo.add(entity)

    # Rollback before commit
    repo.rollback()

    result = repo.get(test_id)
    assert result is None
