"""Tests for scan job definition."""

from lumina.jobs.definitions.scan import scan_job
from lumina.jobs.framework import REGISTRY


def test_scan_job_registered():
    """Scan job should be in global registry."""
    assert REGISTRY.get("scan") is not None
    assert scan_job.name == "scan"


def test_scan_job_has_required_functions():
    """Scan job should have discover and process."""
    assert callable(scan_job.discover)
    assert callable(scan_job.process)


def test_scan_job_configuration():
    """Scan job should have appropriate settings."""
    assert scan_job.batch_size == 500
    assert scan_job.max_workers == 4
    assert scan_job.finalize is not None
