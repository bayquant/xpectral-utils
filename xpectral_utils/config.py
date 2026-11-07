"""Settings shared across xpectral_utils."""

# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------

# Standard library imports
from pathlib import Path

# -----------------------------------------------------------------------------
# Globals and constants
# -----------------------------------------------------------------------------

__all__ = ["DEFAULT_CACHE_DIR"]

# Root under which each feature keeps its cached data in its own subfolder.
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "xpectral"
