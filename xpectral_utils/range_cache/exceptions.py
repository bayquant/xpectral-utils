"""Exceptions raised by the range cache."""

# -----------------------------------------------------------------------------
# Globals and constants
# -----------------------------------------------------------------------------

__all__ = ["DecoratorConfigError", "InvalidRangeError", "RangeCacheError"]

# -----------------------------------------------------------------------------
# General API
# -----------------------------------------------------------------------------


class RangeCacheError(Exception):
    """Base class for all range cache errors."""


class InvalidRangeError(RangeCacheError, ValueError):
    """The requested range is empty or inverted (``start >= end``)."""


class DecoratorConfigError(RangeCacheError, TypeError):
    """The decorator's ``start``, ``end`` or ``key`` do not fit the signature."""
