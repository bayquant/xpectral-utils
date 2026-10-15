"""Sliding-window rate limiter for throttling API calls."""

# ----------------------------------------------------------------------------
# Imports
# ----------------------------------------------------------------------------

# Standard library imports
import logging
import time
from collections import deque

# ----------------------------------------------------------------------------
# Globals and constants
# ----------------------------------------------------------------------------

__all__ = ["RateLimiter"]

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# General API
# ----------------------------------------------------------------------------


class RateLimiter:
    """Allow at most ``calls`` acquisitions per ``per_seconds`` window.

    Call :meth:`acquire` before each request. It returns immediately while the
    window has room, and otherwise blocks until the oldest call leaves the
    window.

    Args:
        calls: Maximum acquisitions allowed in one window.
        per_seconds: Window length in seconds.

    Raises:
        ValueError: If ``calls`` or ``per_seconds`` is not positive.
    """

    def __init__(self, calls: int, per_seconds: float):
        if calls <= 0 or per_seconds <= 0:
            raise ValueError("calls and per_seconds must be positive")
        self.calls = calls
        self.per_seconds = per_seconds
        self._hits: deque[float] = deque()

    def acquire(self) -> None:
        """Block until a call is allowed, then record it."""
        now = time.monotonic()
        window_start = now - self.per_seconds

        while self._hits and self._hits[0] <= window_start:
            self._hits.popleft()

        if len(self._hits) >= self.calls:
            sleep_for = self.per_seconds - (now - self._hits[0])
            if sleep_for > 0:
                logger.info("sleeping for %.0f seconds", sleep_for)
                time.sleep(sleep_for)
            self.acquire()
            return

        self._hits.append(time.monotonic())
