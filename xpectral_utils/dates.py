"""Date and datetime normalization helpers."""

# ----------------------------------------------------------------------------
# Imports
# ----------------------------------------------------------------------------

# Standard library imports
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

# ----------------------------------------------------------------------------
# Globals and constants
# ----------------------------------------------------------------------------

__all__ = [
    "NS_PER_DAY",
    "NS_PER_HOUR",
    "NS_PER_MINUTE",
    "NS_PER_SECOND",
    "from_unix_ns",
    "localize",
    "to_date",
    "to_datetime",
    "to_unix_ns",
]

NS_PER_SECOND = 1_000_000_000
NS_PER_MINUTE = 60 * NS_PER_SECOND
NS_PER_HOUR = 60 * NS_PER_MINUTE
NS_PER_DAY = 24 * NS_PER_HOUR

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Bounds for integer nanosecond input. Seconds, milliseconds and microseconds
# for any modern date are all below the minimum (1973-03-03), so a unit mistake
# fails loudly instead of silently becoming a 1970 timestamp.
_MIN_UNIX_NS = 10**17
_MAX_UNIX_NS = 2**63 - 1

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
        TypeError: If ``value`` is not a string or a ``date``. This includes a
            ``datetime`` (and ``pd.Timestamp``, which subclasses it) as well as
            ints, floats and ``None``.
        ValueError: If ``value`` is a malformed string.
    """
    # datetime is a subclass of date, so it must be rejected before the date
    # check below. pd.Timestamp subclasses datetime, so it fails here too: it
    # carries a time of day, which makes it an instant rather than a calendar
    # day. Convert explicitly with ``ts.date()`` if a day is what you mean.
    if isinstance(value, datetime):
        raise TypeError("expected a date, got a datetime")
    if isinstance(value, str):
        return date.fromisoformat(value)
    if not isinstance(value, date):
        raise TypeError(f"expected a str or date, got {type(value).__name__}")
    return value


def to_datetime(value: str | datetime) -> datetime:
    """Normalize an instant to a timezone-aware ``datetime`` in UTC.

    Only the stdlib ``datetime`` is accepted, not its subclasses. In particular
    ``pd.Timestamp`` is rejected: it carries nanoseconds that a ``datetime``
    cannot hold, so converting it would silently drop the last three digits.
    Pass its ``.value`` (always UTC nanoseconds) to :func:`to_unix_ns` instead.

    Args:
        value: ISO 8601 string with an offset (``2024-03-01T14:30:00Z``) or an
            aware ``datetime``.

    Returns:
        The instant as an aware ``datetime`` in UTC.

    Raises:
        TypeError: If ``value`` is not a string or a plain ``datetime``. This
            covers a bare ``date`` (no time of day) and ``datetime`` subclasses
            such as ``pd.Timestamp``.
        ValueError: If ``value`` is naive or a malformed string.
    """
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    elif type(value) is not datetime:
        raise TypeError(
            f"expected a str or a plain datetime, got {type(value).__name__}; "
            "for pd.Timestamp pass its .value (UTC nanoseconds) to to_unix_ns"
        )
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def localize(value: datetime, tz: str) -> datetime:
    """Attach a timezone to a naive wall-clock ``datetime``.

    Use this to express "10am New York" explicitly before passing it to
    :func:`to_datetime` or :func:`to_unix_ns`. An ambiguous time (the repeated
    hour when clocks fall back) resolves to its first occurrence.

    Args:
        value: Naive ``datetime`` holding the wall-clock time in ``tz``.
        tz: IANA timezone name (``America/New_York``).

    Returns:
        The same wall-clock time as an aware ``datetime`` in ``tz``.

    Raises:
        ValueError: If ``value`` is already timezone-aware.
        zoneinfo.ZoneInfoNotFoundError: If ``tz`` is not a known timezone.
    """
    if value.tzinfo is not None:
        raise ValueError("datetime is already timezone-aware")
    return value.replace(tzinfo=ZoneInfo(tz))


def to_unix_ns(value: int | str | datetime) -> int:
    """Normalize an instant to integer nanoseconds since the UNIX epoch (UTC).

    Integers are taken as nanoseconds already and only range-checked. Strings
    and datetimes follow the rules of :func:`to_datetime`, so they must be
    timezone-aware, plain ``datetime`` objects (``pd.Timestamp`` is rejected),
    and have microsecond resolution at best. Use integers for anything that
    needs nanoseconds.

    Args:
        value: Nanoseconds since the epoch, an ISO 8601 string with an offset,
            or an aware ``datetime``.

    Returns:
        The instant as integer nanoseconds since the epoch.

    Raises:
        TypeError: If ``value`` is not an int, a string, or a ``datetime``.
        ValueError: If an integer is outside the plausible nanosecond range, or
            a string or datetime is naive or malformed.
    """
    if isinstance(value, int):
        if not _MIN_UNIX_NS <= value <= _MAX_UNIX_NS:
            raise ValueError(f"{value} is not plausible UNIX nanoseconds")
        return value
    # Integer division keeps this exact; float seconds would lose precision.
    return (to_datetime(value) - _EPOCH) // timedelta(microseconds=1) * 1000


def from_unix_ns(value: int) -> datetime:
    """Convert integer UNIX nanoseconds to an aware ``datetime`` in UTC.

    Args:
        value: Nanoseconds since the epoch.

    Returns:
        The instant as an aware UTC ``datetime``, truncated to microseconds
        (the resolution of ``datetime``). Keep the integer when the last three
        digits matter.

    Raises:
        ValueError: If ``value`` is outside the plausible nanosecond range.
    """
    return _EPOCH + timedelta(microseconds=to_unix_ns(value) // 1000)
