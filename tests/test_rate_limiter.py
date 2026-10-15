# ----------------------------------------------------------------------------
# Imports
# ----------------------------------------------------------------------------

# Standard library imports
import logging

# Third-party imports
import pytest

# First-party imports
from xpectral_utils import rate_limiter
from xpectral_utils.rate_limiter import RateLimiter

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


class FakeClock:
    """Stands in for the ``time`` module: sleeping only advances the clock."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(rate_limiter, "time", fake)
    return fake


# ----------------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("calls", "per_seconds"),
    [(0, 1), (-1, 1), (1, 0), (1, -1.0)],
)
def test_rejects_non_positive_arguments(calls, per_seconds):
    with pytest.raises(ValueError):
        RateLimiter(calls=calls, per_seconds=per_seconds)


def test_allows_calls_within_the_window_without_sleeping(clock):
    limiter = RateLimiter(calls=3, per_seconds=10)

    for _ in range(3):
        limiter.acquire()

    assert clock.sleeps == []


def test_blocks_until_the_oldest_call_leaves_the_window(clock):
    limiter = RateLimiter(calls=2, per_seconds=10)

    for _ in range(3):
        limiter.acquire()

    assert clock.sleeps == [10.0]


def test_does_not_sleep_once_the_window_has_passed(clock):
    limiter = RateLimiter(calls=2, per_seconds=10)
    limiter.acquire()
    limiter.acquire()

    clock.now = 10.5
    limiter.acquire()

    assert clock.sleeps == []


def test_logs_when_it_sleeps(clock, caplog):
    limiter = RateLimiter(calls=1, per_seconds=5)
    limiter.acquire()

    with caplog.at_level(logging.INFO, logger="xpectral_utils.rate_limiter"):
        limiter.acquire()

    assert "sleeping for 5 seconds" in caplog.text
