"""On-disk range cache (install ``xpectral-utils[cache]``)."""

# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------

# Standard library imports
import datetime
import functools
import inspect
import json
import os
import tempfile
import time
from collections.abc import Callable
from collections.abc import Sequence

# Third-party imports
import pyarrow as pa
import pyarrow.parquet as pq

# First-party imports
from xpectral_utils.range_cache.exceptions import (
    InvalidRangeError,  # goes agains rules for relative imports
)

# -----------------------------------------------------------------------------
# Globals and constants
# -----------------------------------------------------------------------------

__all__ = ["range_cache"]

_RANGE_CACHE_DIR = "./xpectral_utils/range_cache"

# -----------------------------------------------------------------------------
# General API
# -----------------------------------------------------------------------------


def range_cache(
    start_param: str, end_param: str, key_params: Sequence[str]
) -> Callable:
    """Decorator factory: build a decorator adding an on-disk range cache.

    ``start_param`` and ``end_param`` name the parameters holding the range
    bounds in UNIX nanoseconds (UTC), and ``key_params`` names the parameters
    whose values form the manifest tree, in order. Each decorated function gets
    its own directory and manifest, so different functions never collide.
    """

    def decorator(func: Callable) -> Callable:
        signature = inspect.signature(func)
        for name in (start_param, end_param, *key_params):
            if name not in signature.parameters:
                raise TypeError(f"{func.__qualname__} has no parameter {name!r}.")
        func_dir = os.path.join(
            _RANGE_CACHE_DIR, f"{func.__module__}.{func.__qualname__}"
        )
        manifest_path = os.path.join(func_dir, "manifest.json")

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            arguments = bound.arguments

            key_values = [str(arguments[name]) for name in key_params]
            start, end = arguments[start_param], arguments[end_param]

            if start >= end:
                raise InvalidRangeError("Start must be less than end.")

            manifest = _read_manifest(manifest_path)

            tree = manifest
            for part in key_values[:-1]:
                tree = tree.setdefault(part, {})
            segments = tree.setdefault(key_values[-1], [])

            covered, uncovered = _split_coverage(segments, start, end)

            # get cached data

            ts_event = time.time_ns()
            for gap in uncovered:
                # fetch new data

                # convert to the standard format

                segment_path = os.path.join(
                    *key_values, f"{gap['start']}-{gap['end']}.parquet"
                )
                _write_parquet(func_dir, segment_path)
                segments.append(
                    {
                        "start": gap["start"],
                        "end": gap["end"],
                        "path": segment_path,
                        "ts_event": ts_event,
                    }
                )

            # Save before combining: combining can fail, and the fetched
            # segments are already on disk. Skip when nothing was added.
            if uncovered:
                _write_manifest(manifest_path, manifest)

            # combine data, then trim to [start, end) since cached segments
            # can extend past the request

            # return combined data

        return wrapper

    return decorator


# -----------------------------------------------------------------------------
# Private API
# -----------------------------------------------------------------------------


def _split_coverage(
    segments: list[dict], start: int, end: int
) -> tuple[list[dict], list[dict]]:
    """Split ``[start, end)`` into cached and missing ranges."""

    segments = sorted(segments, key=lambda segment: segment["start"], reverse=False)
    cursor = start
    covered, uncovered = [], []
    for segment in segments:
        segment_start, segment_end = segment["start"], segment["end"]
        if segment_end <= start:
            continue
        if segment_start >= end:
            break
        _start, _end = max(segment_start, start), min(segment_end, end)
        if cursor < _start:
            uncovered.append({"start": cursor, "end": _start})
        covered.append({"start": _start, "end": _end})
        cursor = _end
    if cursor < end:
        uncovered.append({"start": cursor, "end": end})

    return covered, uncovered


def _read_manifest(manifest_path: str) -> dict:
    """Load the manifest, or an empty one if it does not exist yet."""

    try:
        with open(manifest_path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _write_manifest(manifest_path: str, manifest: dict) -> None:
    """Atomically replace the manifest so readers never see a partial file.

    The temp file must share a directory with the target for the rename to
    be atomic.
    """

    manifest_dir = os.path.dirname(manifest_path)
    os.makedirs(manifest_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=manifest_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(manifest, f, indent=4, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, manifest_path)
    except BaseException:
        os.unlink(tmp_path)
        raise


def _write_parquet(func_dir: str, segment_path: str) -> None:
    """Write an empty parquet file at ``segment_path``, relative to ``func_dir``."""

    full_path = os.path.join(func_dir, segment_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    pq.write_table(pa.table({}), full_path)


# Tests:
# 1. start date is higher than end date
# 2. start or end date is equal to None
# 3. Add a test for merging segments in the manifest

# TODO:
# 1. Add logging to the range_cache function to log when a cache hit or miss occurs.
# 2. Save paths support.
# 3. Sha support.
# 4. Check what happens when I request a single date.

if __name__ == "__main__":

    def ns(year: int, month: int, day: int) -> int:
        """UTC midnight of a calendar date as UNIX nanoseconds."""
        utc = datetime.timezone.utc
        return int(datetime.datetime(year, month, day, tzinfo=utc).timestamp()) * 10**9

    @range_cache(start_param="start", end_param="end", key_params=["kind", "symbol"])
    def fetch(kind: str, symbol: str, start: int, end: int): ...

    @range_cache(start_param="start", end_param="end", key_params=["symbol"])
    def fetch_other(symbol: str, start: int, end: int): ...

    # Empty cache: everything is uncovered.
    print(fetch("bar", "aapl", ns(2026, 1, 20), ns(2026, 3, 10)))
    # Fully covered by the segment above.
    print(fetch("bar", "aapl", ns(2026, 2, 20), ns(2026, 3, 10)))
    # Spans the whole cache: gaps on both sides.
    print(fetch("bar", "aapl", ns(2026, 1, 1), ns(2026, 4, 1)))
    # Same symbol under a different kind is cached independently.
    print(fetch("range", "aapl", ns(2026, 1, 20), ns(2026, 3, 10)))
    # A different function has its own manifest, so nothing is cached yet.
    print(fetch_other("aapl", ns(2026, 1, 20), ns(2026, 3, 10)))
    # Invalid: start >= end.
    try:
        fetch("bar", "aapl", ns(2026, 3, 10), ns(2026, 3, 10))
    except InvalidRangeError as error:
        print("InvalidRangeError:", error)
