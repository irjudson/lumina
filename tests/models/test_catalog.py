"""Tests for Catalog model."""

import uuid

from lumina.models.catalog import Catalog, CatalogCreate


def test_catalog_create_generates_uuid():
    """Catalog should auto-generate UUID."""
    catalog = Catalog(
        name="Test Catalog",
        schema_name="cat_test",
        source_directories=["/photos"],
    )
    assert catalog.id is not None
    assert isinstance(catalog.id, uuid.UUID)


def test_catalog_create_schema():
    """CatalogCreate should validate input."""
    data = CatalogCreate(
        name="My Photos",
        source_directories=["/home/user/photos"],
    )
    assert data.name == "My Photos"
    assert data.source_directories == ["/home/user/photos"]
