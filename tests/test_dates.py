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
from xpectral_utils.dates import to_date
from xpectral_utils.dates import to_datetime

# ----------------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------------


def test_to_date_parses_iso_string():
    assert to_date("2024-03-01") == date(2024, 3, 1)


def test_to_date_passes_date_through():
    assert to_date(date(2024, 3, 1)) == date(2024, 3, 1)


def test_to_date_rejects_datetime():
    with pytest.raises(TypeError):
        to_date(datetime(2024, 3, 1, tzinfo=UTC))


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


def test_to_datetime_rejects_naive_datetime():
    with pytest.raises(ValueError):
        to_datetime(datetime(2024, 3, 1, 14, 30))


def test_to_datetime_rejects_naive_string():
    with pytest.raises(ValueError):
        to_datetime("2024-03-01T14:30:00")
