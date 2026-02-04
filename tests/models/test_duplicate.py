"""Tests for Duplicate SQLModels."""

import uuid
from datetime import datetime

import pytest

from lumina.models.duplicate import DuplicateGroup, DuplicateMember, SimilarityType


class TestSimilarityType:
    def test_similarity_type_enum(self):
        assert SimilarityType.EXACT.value == "exact"
        assert SimilarityType.PERCEPTUAL.value == "perceptual"

    def test_similarity_type_members(self):
        assert len(SimilarityType) == 2
        assert SimilarityType.EXACT in SimilarityType
        assert SimilarityType.PERCEPTUAL in SimilarityType


class TestDuplicateGroup:
    def test_duplicate_group_creation(self):
        group = DuplicateGroup(
            catalog_id=uuid.uuid4(),
            primary_image_id="img-001",
            similarity_type=SimilarityType.PERCEPTUAL,
            confidence=95,
        )
        assert group.reviewed is False
        assert group.confidence == 95
        assert group.similarity_type == SimilarityType.PERCEPTUAL

    def test_duplicate_group_defaults(self):
        catalog_id = uuid.uuid4()
        group = DuplicateGroup(
            catalog_id=catalog_id,
            primary_image_id="img-primary",
            similarity_type=SimilarityType.EXACT,
            confidence=100,
        )
        assert group.catalog_id == catalog_id
        assert group.primary_image_id == "img-primary"
        assert group.reviewed is False
        assert group.id is None  # Auto-increment, None until DB insert

    def test_duplicate_group_exact_match(self):
        group = DuplicateGroup(
            catalog_id=uuid.uuid4(),
            primary_image_id="img-exact-001",
            similarity_type=SimilarityType.EXACT,
            confidence=100,
        )
        assert group.similarity_type == SimilarityType.EXACT
        assert group.confidence == 100

    def test_duplicate_group_reviewed(self):
        group = DuplicateGroup(
            catalog_id=uuid.uuid4(),
            primary_image_id="img-reviewed",
            similarity_type=SimilarityType.PERCEPTUAL,
            confidence=85,
            reviewed=True,
        )
        assert group.reviewed is True

    def test_duplicate_group_created_at_default(self):
        before = datetime.utcnow()
        group = DuplicateGroup(
            catalog_id=uuid.uuid4(),
            primary_image_id="img-time",
            similarity_type=SimilarityType.PERCEPTUAL,
            confidence=90,
        )
        after = datetime.utcnow()
        assert before <= group.created_at <= after


class TestDuplicateMember:
    def test_duplicate_member_creation(self):
        member = DuplicateMember(
            group_id=1,
            image_id="img-member-001",
            similarity_score=92,
        )
        assert member.group_id == 1
        assert member.image_id == "img-member-001"
        assert member.similarity_score == 92

    def test_duplicate_member_composite_key(self):
        member = DuplicateMember(
            group_id=5,
            image_id="img-composite",
            similarity_score=88,
        )
        # Both fields are part of primary key
        assert member.group_id == 5
        assert member.image_id == "img-composite"

    def test_duplicate_member_perfect_match(self):
        member = DuplicateMember(
            group_id=1,
            image_id="img-perfect",
            similarity_score=100,
        )
        assert member.similarity_score == 100
