"""Date and datetime normalization helpers."""

# ----------------------------------------------------------------------------
# Imports
# ----------------------------------------------------------------------------

# Standard library imports
from datetime import UTC
from datetime import date
from datetime import datetime

# ----------------------------------------------------------------------------
# Globals and constants
# ----------------------------------------------------------------------------

__all__ = ["to_date", "to_datetime"]

# ----------------------------------------------------------------------------
# General API
# ----------------------------------------------------------------------------


def to_date(value: str | date) -> date:
    """Normalize a calendar day to a ``date``.

    Args:
        value: ISO 8601 date string (``2024-03-01``) or a ``date``.

    Returns:
        The calendar day as a ``date``.

    Raises:
        TypeError: If ``value`` is a ``datetime``.
        ValueError: If ``value`` is a malformed string.
    """
    # datetime is a subclass of date, so reject it before anything else.
    if isinstance(value, datetime):
        raise TypeError("expected a date, got a datetime")
    if isinstance(value, str):
        return date.fromisoformat(value)
    return value


def to_datetime(value: str | datetime) -> datetime:
    """Normalize an instant to a timezone-aware ``datetime`` in UTC.

    Args:
        value: ISO 8601 string with an offset (``2024-03-01T14:30:00Z``) or an
            aware ``datetime``.

    Returns:
        The instant as an aware ``datetime`` in UTC.

    Raises:
        ValueError: If ``value`` is naive or a malformed string.
    """
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)
