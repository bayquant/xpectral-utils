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
    """A ``range_cache`` setting does not fit the decorated function.

    Raised when ``start_param``, ``end_param`` or an entry of ``key_params``
    is not a parameter of the function.
    """
