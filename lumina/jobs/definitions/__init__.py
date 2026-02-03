"""Job definitions - import all to register with global registry."""

from . import duplicates, scan

# Bursts will be added in subsequent task
# from . import bursts

__all__ = ["duplicates", "scan"]
