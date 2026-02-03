"""Tests for Tag SQLModels."""

import uuid
from datetime import datetime

import pytest

from lumina.models.tag import ImageTag, Tag, TagSource


class TestTagSource:
    def test_tag_source_enum(self):
        assert TagSource.MANUAL.value == "manual"
        assert TagSource.OPENCLIP.value == "openclip"
        assert TagSource.OLLAMA.value == "ollama"
        assert TagSource.COMBINED.value == "combined"

    def test_tag_source_members(self):
        assert len(TagSource) == 4
        assert TagSource.MANUAL in TagSource
        assert TagSource.OPENCLIP in TagSource
        assert TagSource.OLLAMA in TagSource
        assert TagSource.COMBINED in TagSource


class TestTag:
    def test_tag_creation(self):
        tag = Tag(catalog_id=uuid.uuid4(), name="sunset", category="scene")
        assert tag.name == "sunset"
        assert tag.category == "scene"

    def test_tag_defaults(self):
        catalog_id = uuid.uuid4()
        tag = Tag(catalog_id=catalog_id, name="beach")
        assert tag.catalog_id == catalog_id
        assert tag.name == "beach"
        assert tag.category is None
        assert tag.parent_id is None
        assert tag.description is None
        assert tag.id is None  # Auto-increment, None until DB insert

    def test_tag_with_parent(self):
        tag = Tag(
            catalog_id=uuid.uuid4(),
            name="golden_retriever",
            category="animal",
            parent_id=5,  # Parent tag ID for "dog"
        )
        assert tag.parent_id == 5

    def test_tag_with_synonyms(self):
        tag = Tag(
            catalog_id=uuid.uuid4(),
            name="sunset",
            category="scene",
            synonyms=["dusk", "sundown", "evening"],
        )
        assert tag.synonyms == ["dusk", "sundown", "evening"]
        assert len(tag.synonyms) == 3

    def test_tag_with_description(self):
        tag = Tag(
            catalog_id=uuid.uuid4(),
            name="landscape",
            category="genre",
            description="Photographs of natural scenery",
        )
        assert tag.description == "Photographs of natural scenery"

    def test_tag_created_at_default(self):
        before = datetime.utcnow()
        tag = Tag(catalog_id=uuid.uuid4(), name="test")
        after = datetime.utcnow()
        assert before <= tag.created_at <= after


class TestImageTag:
    def test_image_tag_creation(self):
        image_tag = ImageTag(
            image_id="img-001",
            tag_id=10,
        )
        assert image_tag.image_id == "img-001"
        assert image_tag.tag_id == 10
        assert image_tag.confidence == 1.0
        assert image_tag.source == TagSource.MANUAL

    def test_image_tag_defaults(self):
        image_tag = ImageTag(image_id="img-default", tag_id=5)
        assert image_tag.confidence == 1.0
        assert image_tag.source == TagSource.MANUAL
        assert image_tag.openclip_confidence is None
        assert image_tag.ollama_confidence is None

    def test_image_tag_openclip_source(self):
        image_tag = ImageTag(
            image_id="img-clip",
            tag_id=20,
            confidence=0.87,
            source=TagSource.OPENCLIP,
            openclip_confidence=0.87,
        )
        assert image_tag.source == TagSource.OPENCLIP
        assert image_tag.openclip_confidence == 0.87

    def test_image_tag_ollama_source(self):
        image_tag = ImageTag(
            image_id="img-ollama",
            tag_id=25,
            confidence=0.92,
            source=TagSource.OLLAMA,
            ollama_confidence=0.92,
        )
        assert image_tag.source == TagSource.OLLAMA
        assert image_tag.ollama_confidence == 0.92

    def test_image_tag_combined_source(self):
        image_tag = ImageTag(
            image_id="img-combined",
            tag_id=30,
            confidence=0.90,
            source=TagSource.COMBINED,
            openclip_confidence=0.85,
            ollama_confidence=0.95,
        )
        assert image_tag.source == TagSource.COMBINED
        assert image_tag.openclip_confidence == 0.85
        assert image_tag.ollama_confidence == 0.95
        assert image_tag.confidence == 0.90

    def test_image_tag_composite_key(self):
        image_tag = ImageTag(
            image_id="img-composite-key",
            tag_id=40,
        )
        # Both fields are part of primary key
        assert image_tag.image_id == "img-composite-key"
        assert image_tag.tag_id == 40

    def test_image_tag_created_at_default(self):
        before = datetime.utcnow()
        image_tag = ImageTag(image_id="img-time", tag_id=1)
        after = datetime.utcnow()
        assert before <= image_tag.created_at <= after
