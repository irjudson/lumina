"""
Job-level conftest: provides a db_session that commits to the actual test
database (without SAVEPOINT isolation) for tests that call job functions
which internally use get_db_context().

This works around the SAVEPOINT gotcha documented in MEMORY.md where
get_db_context() opens a new connection that cannot see data written through
db_session's SAVEPOINT.
"""

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db_session(engine, tables_created):
    """
    Provide a database session that commits to the actual test DB.

    Unlike the root conftest db_session which uses SAVEPOINT isolation,
    this version commits real transactions so that job code using
    get_db_context() can see the test data.

    Cleanup: we track created catalog IDs and delete them after the test.
    """
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()

    # Track object primary keys added so we can clean up
    added_catalog_ids = []
    added_image_ids = []

    original_add = session.add

    def tracked_add(obj):
        from lumina.db.models import Catalog, Image

        original_add(obj)
        if isinstance(obj, Catalog) and obj.id not in added_catalog_ids:
            added_catalog_ids.append(obj.id)
        elif isinstance(obj, Image) and obj.id not in added_image_ids:
            added_image_ids.append(obj.id)

    session.add = tracked_add

    yield session

    # Cleanup: remove anything we added
    try:
        session.rollback()  # Undo any uncommitted changes first
        if added_image_ids:
            from lumina.db.models import Image

            session.query(Image).filter(Image.id.in_(added_image_ids)).delete(
                synchronize_session=False
            )
            session.commit()
        if added_catalog_ids:
            from lumina.db.models import Catalog

            session.query(Catalog).filter(Catalog.id.in_(added_catalog_ids)).delete(
                synchronize_session=False
            )
            session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()
