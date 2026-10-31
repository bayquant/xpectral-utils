"""On-disk range cache (install ``xpectral-utils[cache]``)."""

# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------

# Standard library imports
import datetime
import json
import os
import tempfile
import time

# Third-party imports
import polars as pl

# -----------------------------------------------------------------------------
# Globals and constants
# -----------------------------------------------------------------------------

__all__ = ["range_cache"]

_RANGE_CACHE_PATH = "./xpectral_utils/range_cache/manifest.json"

# -----------------------------------------------------------------------------
# General API
# -----------------------------------------------------------------------------


def range_cache(kind: str, symbol: str, start: int, end: int) -> dict:
    """Cache lookup over ``[start, end)`` in UNIX nanoseconds (UTC)."""

    # Range is inclusive of start but not end to avoid overlap with next range.
    if start >= end:
        raise ValueError("Start must be less than end.")

    with open(_RANGE_CACHE_PATH) as f:
        manifest = json.load(f)

    segments = manifest.setdefault(kind, {}).setdefault(symbol, [])
    covered, uncovered = _split_coverage(segments, start, end)
    now = time.time_ns()
    for gap in uncovered:
        path = f"{kind}/{symbol}/{gap['start']}-{gap['end']}.parquet"
        _write_parquet(path)
        segments.append(
            {"start": gap["start"], "end": gap["end"], "path": path, "ts_event": now}
        )
    _write_manifest(manifest)

    return covered, uncovered


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


def _write_manifest(manifest: dict) -> None:
    """Atomically replace the manifest so readers never see a partial file.

    The temp file must share a directory with the target for the rename to
    be atomic.
    """

    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(_RANGE_CACHE_PATH), suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(manifest, f, indent=4, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, _RANGE_CACHE_PATH)
    except BaseException:
        os.unlink(tmp_path)
        raise


def _write_parquet(path: str) -> None:
    """Write an empty parquet file at ``path``, relative to the cache root."""

    full_path = os.path.join(os.path.dirname(_RANGE_CACHE_PATH), path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    pl.DataFrame().write_parquet(full_path)


# Tests:
# 1. start date is higher than end date
# 2. start or end date is equal to None
# 3. Add a test for merging segments in the manifest

# TODO:
# 1. Add logging to the range_cache function to log when a cache hit or miss occurs.
# 2. Save paths support.
# 3. Sha support.

if __name__ == "__main__":

    def ns(year: int, month: int, day: int) -> int:
        """UTC midnight of a calendar date as UNIX nanoseconds."""
        utc = datetime.timezone.utc
        return int(datetime.datetime(year, month, day, tzinfo=utc).timestamp()) * 10**9

    # Empty cache: everything is uncovered.
    print(range_cache("bar", "aapl", ns(2026, 1, 20), ns(2026, 3, 10)))
    # Fully covered by the segment above.
    print(range_cache("bar", "aapl", ns(2026, 2, 20), ns(2026, 3, 10)))
    # Extends past the cached end: one gap on the right.
    print(range_cache("bar", "aapl", ns(2026, 3, 1), ns(2026, 3, 20)))
    # Extends before the cached start: one gap on the left.
    print(range_cache("bar", "aapl", ns(2026, 1, 10), ns(2026, 1, 25)))
    # Spans the whole cache: gaps on both sides.
    print(range_cache("bar", "aapl", ns(2026, 1, 1), ns(2026, 4, 1)))
    # Hole in the middle: two disjoint segments, then a request across both.
    range_cache("bar", "ibm", ns(2023, 1, 1), ns(2023, 1, 10))
    range_cache("bar", "ibm", ns(2023, 2, 1), ns(2023, 2, 10))
    print(range_cache("bar", "ibm", ns(2023, 1, 5), ns(2023, 2, 5)))
    # Same symbol under a different kind is cached independently.
    print(range_cache("range", "ibm", ns(2023, 1, 1), ns(2023, 1, 10)))
    # Adjacent request: end of cache equals start of request, so no overlap.
    print(range_cache("range", "ibm", ns(2023, 1, 10), ns(2023, 1, 15)))
    # Invalid: start >= end.
    try:
        range_cache("bar", "aapl", ns(2026, 3, 10), ns(2026, 3, 10))
    except ValueError as error:
        print("ValueError:", error)
