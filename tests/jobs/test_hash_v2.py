def test_discover_images_needing_hashes_uses_provider():
    from lumina.jobs.definitions.hash_v2 import discover_images_needing_hashes

    result = discover_images_needing_hashes(
        "cat-1", images_provider=lambda cid: ["a", "b"]
    )
    assert result == ["a", "b"]


def test_compute_hashes_v2_handles_missing_image():
    from unittest.mock import MagicMock, patch

    from lumina.jobs.definitions.hash_v2 import compute_hashes_v2

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = None
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_session)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    with patch("lumina.db.connection.get_db_context", return_value=mock_ctx):
        result = compute_hashes_v2(
            "nonexistent-id-xyz", "00000000-0000-0000-0000-000000000000"
        )

    assert result["success"] is False
    assert "error" in result


def test_finalize_hash_v2_returns_counts():
    from unittest.mock import MagicMock, patch

    from lumina.jobs.definitions.hash_v2 import finalize_hash_v2

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = None
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_session)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    with patch("lumina.db.connection.get_db_context", return_value=mock_ctx):
        results = [
            {"success": True},
            {"success": True},
            {"success": False, "error": "x"},
        ]
        out = finalize_hash_v2(results, "00000000-0000-0000-0000-000000000000")

    assert out["hashed"] == 2
    assert out["failed"] == 1


def test_job_registered():
    import lumina.jobs.definitions.hash_v2  # noqa: F401
    from lumina.jobs import framework

    assert "hash_images_v2" in framework.REGISTRY._jobs
