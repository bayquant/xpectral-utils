# ----------------------------------------------------------------------------
# Imports
# ----------------------------------------------------------------------------

# Standard library imports
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone

# Third-party imports
import pytest

# First-party imports
from xpectral_utils.dates import NS_PER_DAY
from xpectral_utils.dates import NS_PER_SECOND
from xpectral_utils.dates import from_unix_ns
from xpectral_utils.dates import localize
from xpectral_utils.dates import to_date
from xpectral_utils.dates import to_datetime
from xpectral_utils.dates import to_unix_ns

# ----------------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------------

class _Timestamp(datetime):
    """Stand-in for ``pd.Timestamp``: a ``datetime`` subclass."""


def test_to_date_parses_iso_string():
    assert to_date("2024-03-01") == date(2024, 3, 1)


def test_to_date_passes_date_through():
    assert to_date(date(2024, 3, 1)) == date(2024, 3, 1)


def test_to_date_rejects_datetime():
    with pytest.raises(TypeError):
        to_date(datetime(2024, 3, 1, tzinfo=UTC))


def test_to_date_rejects_int():
    with pytest.raises(TypeError):
        to_date(2026)


def test_to_date_rejects_datetime_subclass():
    # Midnight, so it only "holds a date", but it is still an instant.
    with pytest.raises(TypeError):
        to_date(_Timestamp(2024, 3, 1))


def test_to_date_rejects_malformed_string():
    with pytest.raises(ValueError):
        to_date("not-a-date")


def test_to_datetime_parses_zulu_string():
    assert to_datetime("2024-03-01T14:30:00Z") == datetime(
        2024, 3, 1, 14, 30, tzinfo=UTC
    )


def test_to_datetime_converts_offset_to_utc():
    result = to_datetime("2024-03-01T09:30:00-05:00")
    assert result == datetime(2024, 3, 1, 14, 30, tzinfo=UTC)
    assert result.utcoffset() == timedelta(0)


def test_to_datetime_converts_aware_datetime_to_utc():
    value = datetime(2024, 3, 1, 9, 30, tzinfo=timezone(timedelta(hours=-5)))
    assert to_datetime(value) == datetime(2024, 3, 1, 14, 30, tzinfo=UTC)


def test_to_datetime_rejects_naive_string():
    with pytest.raises(ValueError):
        to_datetime("2024-03-01T14:30:00")


def test_to_datetime_rejects_naive_datetime():
    with pytest.raises(ValueError):
        to_datetime(datetime(2024, 3, 1, 14, 30))


def test_to_datetime_rejects_bare_date():
    with pytest.raises(TypeError):
        to_datetime(date(2024, 3, 1))


def test_to_datetime_rejects_datetime_subclass():
    value = _Timestamp(2024, 3, 1, 14, 30, tzinfo=UTC)
    with pytest.raises(TypeError):
        to_datetime(value)


def test_localize_attaches_new_york_offset():
    result = localize(datetime(2024, 1, 2, 10), "America/New_York")
    assert to_datetime(result) == datetime(2024, 1, 2, 15, tzinfo=UTC)


def test_localize_respects_dst():
    result = localize(datetime(2024, 7, 2, 10), "America/New_York")
    assert to_datetime(result) == datetime(2024, 7, 2, 14, tzinfo=UTC)


def test_localize_rejects_aware_datetime():
    with pytest.raises(ValueError):
        localize(datetime(2024, 1, 2, 10, tzinfo=UTC), "America/New_York")


def test_to_unix_ns_rejects_datetime_subclass():
    value = _Timestamp(2024, 3, 1, 14, 30, tzinfo=UTC)
    with pytest.raises(TypeError):
        to_unix_ns(value)


def test_to_unix_ns_from_aware_datetime():
    value = datetime(2024, 1, 2, 15, tzinfo=UTC)
    assert to_unix_ns(value) == 1_704_207_600 * NS_PER_SECOND


def test_to_unix_ns_from_offset_string():
    assert to_unix_ns("2024-01-02T10:00:00-05:00") == 1_704_207_600 * NS_PER_SECOND


def test_to_unix_ns_passes_int_through():
    assert to_unix_ns(1_704_207_600_123_456_789) == 1_704_207_600_123_456_789


@pytest.mark.parametrize("seconds", [1_704_207_600, 1_704_207_600_000])
def test_to_unix_ns_rejects_seconds_and_milliseconds(seconds):
    with pytest.raises(ValueError):
        to_unix_ns(seconds)


def test_to_unix_ns_rejects_naive_datetime():
    with pytest.raises(ValueError):
        to_unix_ns(datetime(2024, 1, 2, 10))


def test_to_unix_ns_rejects_bare_date():
    with pytest.raises(TypeError):
        to_unix_ns(date(2024, 1, 2))


def test_from_unix_ns_round_trips():
    value = datetime(2024, 1, 2, 15, 0, 0, 123456, tzinfo=UTC)
    assert from_unix_ns(to_unix_ns(value)) == value


def test_unix_ns_arithmetic_is_exact():
    end_ns = to_unix_ns("2024-01-02T15:00:00Z")
    assert from_unix_ns(end_ns - 7 * NS_PER_DAY) == datetime(
        2023, 12, 26, 15, tzinfo=UTC
    )
