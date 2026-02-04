"""Tests for Burst SQLModel."""

import uuid
from datetime import datetime

import pytest

from lumina.models.burst import Burst


class TestBurst:
    def test_burst_creation(self):
        burst = Burst(
            catalog_id=uuid.uuid4(),
            image_count=5,
            start_time=datetime(2024, 1, 1, 12, 0, 0),
            end_time=datetime(2024, 1, 1, 12, 0, 3),
            duration_seconds=3.0,
        )
        assert burst.image_count == 5
        assert burst.selection_method == "quality"
        assert burst.duration_seconds == 3.0

    def test_burst_defaults(self):
        catalog_id = uuid.uuid4()
        burst = Burst(
            catalog_id=catalog_id,
            image_count=3,
        )
        assert burst.catalog_id == catalog_id
        assert burst.image_count == 3
        assert burst.selection_method == "quality"
        assert burst.start_time is None
        assert burst.end_time is None
        assert burst.duration_seconds is None
        assert burst.camera_make is None
        assert burst.camera_model is None
        assert burst.best_image_id is None
        assert burst.id is not None  # UUID auto-generated

    def test_burst_with_camera_info(self):
        burst = Burst(
            catalog_id=uuid.uuid4(),
            image_count=10,
            camera_make="Canon",
            camera_model="EOS R5",
        )
        assert burst.camera_make == "Canon"
        assert burst.camera_model == "EOS R5"

    def test_burst_with_best_image(self):
        burst = Burst(
            catalog_id=uuid.uuid4(),
            image_count=7,
            best_image_id="img-best-001",
            selection_method="sharpness",
        )
        assert burst.best_image_id == "img-best-001"
        assert burst.selection_method == "sharpness"

    def test_burst_id_auto_generated(self):
        burst1 = Burst(catalog_id=uuid.uuid4(), image_count=2)
        burst2 = Burst(catalog_id=uuid.uuid4(), image_count=3)
        # Each burst should get a unique ID
        assert burst1.id != burst2.id

    def test_burst_created_at_default(self):
        before = datetime.utcnow()
        burst = Burst(catalog_id=uuid.uuid4(), image_count=1)
        after = datetime.utcnow()
        assert before <= burst.created_at <= after
