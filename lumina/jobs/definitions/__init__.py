"""Job definitions - import all to register with global registry."""

from . import scan

# These will be added in subsequent tasks
# from . import duplicates
# from . import bursts

__all__ = ["scan"]
