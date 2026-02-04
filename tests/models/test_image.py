"""Tests for Image SQLModel."""

import pytest

from lumina.models.image import FileType, Image, ImageRead, ProcessingStatus


class TestProcessingStatus:
    def test_enum_values(self):
        assert ProcessingStatus.pending.value == "pending"
        assert ProcessingStatus.scanning.value == "scanning"
        assert ProcessingStatus.hashing.value == "hashing"
        assert ProcessingStatus.tagging.value == "tagging"
        assert ProcessingStatus.complete.value == "complete"
        assert ProcessingStatus.failed.value == "failed"


class TestFileType:
    def test_enum_values(self):
        assert FileType.image.value == "image"
        assert FileType.video.value == "video"


class TestImage:
    def test_defaults(self):
        img = Image(
            id="test-id",
            catalog_id="00000000-0000-0000-0000-000000000001",
            source_path="/path/to/image.jpg",
            checksum="abc123",
        )
        assert img.file_type == FileType.image
        assert img.status == "active"
        assert img.dates == {}
        assert img.processing_flags == {}
        assert img.metadata_json == {}

    def test_file_type_video(self):
        img = Image(
            id="test-id",
            catalog_id="00000000-0000-0000-0000-000000000001",
            source_path="/path/to/video.mp4",
            checksum="def456",
            file_type=FileType.video,
        )
        assert img.file_type == FileType.video

    def test_optional_fields(self):
        img = Image(
            id="test-id",
            catalog_id="00000000-0000-0000-0000-000000000001",
            source_path="/path/to/image.jpg",
            checksum="abc123",
            size_bytes=1024,
            thumbnail_path="/thumbs/test.jpg",
            dhash="d123",
            ahash="a456",
            whash="w789",
            geohash_4="dr5r",
            geohash_6="dr5r7p",
            geohash_8="dr5r7pab",
            quality_score=85,
            description="A beautiful sunset",
        )
        assert img.size_bytes == 1024
        assert img.thumbnail_path == "/thumbs/test.jpg"
        assert img.dhash == "d123"
        assert img.ahash == "a456"
        assert img.whash == "w789"
        assert img.geohash_4 == "dr5r"
        assert img.geohash_6 == "dr5r7p"
        assert img.geohash_8 == "dr5r7pab"
        assert img.quality_score == 85
        assert img.description == "A beautiful sunset"

    def test_burst_fields(self):
        import uuid

        burst_uuid = uuid.uuid4()
        img = Image(
            id="test-id",
            catalog_id="00000000-0000-0000-0000-000000000001",
            source_path="/path/to/image.jpg",
            checksum="abc123",
            burst_id=burst_uuid,
            burst_sequence=3,
        )
        assert img.burst_id == burst_uuid
        assert img.burst_sequence == 3

    def test_clip_embedding(self):
        embedding = [0.1] * 768
        img = Image(
            id="test-id",
            catalog_id="00000000-0000-0000-0000-000000000001",
            source_path="/path/to/image.jpg",
            checksum="abc123",
            clip_embedding=embedding,
        )
        assert img.clip_embedding == embedding
        assert len(img.clip_embedding) == 768


class TestImageRead:
    def test_image_read_schema(self):
        from datetime import datetime

        now = datetime.utcnow()
        read_data = ImageRead(
            id="test-id",
            catalog_id="00000000-0000-0000-0000-000000000001",
            source_path="/path/to/image.jpg",
            checksum="abc123",
            created_at=now,
            updated_at=now,
        )
        assert read_data.id == "test-id"
        assert read_data.created_at == now
        assert read_data.updated_at == now
