def test_dedup_models_importable():
    from lumina.db.models import (
        ArchivedImage,
        DetectionThreshold,
        DuplicateCandidate,
        DuplicateDecision,
        SuppressionPair,
    )

    assert DuplicateCandidate.__tablename__ == "duplicate_candidates"
    assert DuplicateDecision.__tablename__ == "duplicate_decisions"
    assert ArchivedImage.__tablename__ == "archived_images"
    assert DetectionThreshold.__tablename__ == "detection_thresholds"
    assert SuppressionPair.__tablename__ == "suppression_pairs"
