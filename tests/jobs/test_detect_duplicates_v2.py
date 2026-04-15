"""Tests for detect_duplicates_v2 job."""

from pathlib import Path
from unittest.mock import MagicMock, call, patch


def test_ensure_hashes_skips_when_all_present():
    """_ensure_hashes does nothing when all images already have dhash_16/32."""
    from lumina.jobs.definitions.detect_duplicates_v2 import _ensure_hashes

    session = MagicMock()
    session.execute.return_value.fetchall.return_value = []  # no images need hashing

    count = _ensure_hashes("00000000-0000-0000-0000-000000000001", session)

    assert count == 0
    session.commit.assert_not_called()


def test_ensure_hashes_computes_and_saves(tmp_path):
    """_ensure_hashes computes and persists hashes for images missing them."""
    from PIL import Image as PILImage

    from lumina.jobs.definitions.detect_duplicates_v2 import _ensure_hashes

    img_path = tmp_path / "test.jpg"
    PILImage.new("RGB", (100, 100), color=(50, 100, 150)).save(img_path)

    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [
        MagicMock(id="img-1", source_path=str(img_path)),
    ]

    count = _ensure_hashes("00000000-0000-0000-0000-000000000001", session)

    assert count == 1
    session.commit.assert_called_once()
    # Verify an UPDATE was issued
    update_call_args = session.execute.call_args_list[-1]
    params = update_call_args[0][1]
    assert params["id"] == "img-1"
    assert params["dhash_16"] is not None
    assert len(params["dhash_16"]) == 64  # 256-bit = 64 hex chars


def test_ensure_hashes_tolerates_bad_path():
    """_ensure_hashes logs a warning and skips images with unreadable paths."""
    from lumina.jobs.definitions.detect_duplicates_v2 import _ensure_hashes

    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [
        MagicMock(id="img-bad", source_path="/nonexistent/path.jpg"),
    ]

    count = _ensure_hashes("00000000-0000-0000-0000-000000000001", session)

    assert count == 0
    session.commit.assert_called_once()  # still commits (empty changeset is fine)


def test_job_registered():
    import lumina.jobs.definitions.detect_duplicates_v2  # noqa: F401
    from lumina.jobs import framework

    assert "detect_duplicates_v2" in framework.job_registry._jobs


def test_reprocess_mode_values():
    from lumina.jobs.definitions.detect_duplicates_v2 import ReprocessMode

    assert ReprocessMode.NEW_IMAGES_ONLY.value == "new"
    assert ReprocessMode.THRESHOLD_CHANGED.value == "layer"
    assert ReprocessMode.FULL_RESCAN.value == "full"
