"""Tests for detect_duplicates_v2 job."""


def test_job_registered():
    import lumina.jobs.definitions.detect_duplicates_v2  # noqa: F401
    from lumina.jobs import framework

    assert "detect_duplicates_v2" in framework.job_registry._jobs


def test_reprocess_mode_values():
    from lumina.jobs.definitions.detect_duplicates_v2 import ReprocessMode

    assert ReprocessMode.NEW_IMAGES_ONLY.value == "new"
    assert ReprocessMode.THRESHOLD_CHANGED.value == "layer"
    assert ReprocessMode.FULL_RESCAN.value == "full"
