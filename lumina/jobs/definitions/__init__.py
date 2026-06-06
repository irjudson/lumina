"""Job definitions - import all to register with global registry."""

from . import bursts, camera_import, detect_duplicates_v2, duplicates, hash_v2, scan

__all__ = [
    "bursts",
    "camera_import",
    "detect_duplicates_v2",
    "duplicates",
    "hash_v2",
    "scan",
]
