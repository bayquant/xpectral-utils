"""On-disk range cache (install ``xpectral-utils[cache]``)."""

# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------

# Standard library imports
import datetime
import functools
import inspect
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from collections.abc import Sequence

# Third-party imports
import polars as pl

# First-party imports
from xpectral_utils.config import DEFAULT_CACHE_DIR
from xpectral_utils.range_cache.exceptions import DecoratorConfigError
from xpectral_utils.range_cache.exceptions import InvalidRangeError

# -----------------------------------------------------------------------------
# Globals and constants
# -----------------------------------------------------------------------------

__all__ = ["range_cache"]

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# General API
# -----------------------------------------------------------------------------


def range_cache(
    start_param: str, end_param: str, key_params: Sequence[str], time_column: str
) -> Callable:
    """Decorator factory: build a decorator adding an on-disk range cache.

    ``start_param`` and ``end_param`` name the parameters holding the range
    bounds in UNIX nanoseconds (UTC), and ``key_params`` names the parameters
    whose values form the manifest tree, in order. ``time_column`` names the
    column of the returned data that holds each row's time, used to trim rows
    to the requested range. The decorated function must return a polars DataFrame or LazyFrame.
    Each decorated function gets its own directory and manifest, so different
    functions never collide.
    """

    def decorator(func: Callable) -> Callable:
        signature = inspect.signature(func)
        for name in (start_param, end_param, *key_params):
            if name not in signature.parameters:
                raise DecoratorConfigError(
                    f"{func.__qualname__} has no parameter {name!r}."
                )
        func_dir = os.path.join(
            DEFAULT_CACHE_DIR,
            "range_cache",
            f"{func.__module__}.{func.__qualname__}",
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

            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)
            except FileNotFoundError:
                manifest = {}

            tree = manifest
            for part in key_values[:-1]:
                tree = tree.setdefault(part, {})
            segments = tree.setdefault(key_values[-1], [])

            pieces = _split_range(segments, start, end)

            frames = []
            ts_event = time.time_ns()
            updated = False
            for piece in pieces:
                if piece["path"] is not None:
                    logger.debug(
                        "hit: %s %s [%d, %d)",
                        func.__qualname__,
                        key_values,
                        piece["start"],
                        piece["end"],
                    )
                    df = pl.read_parquet(os.path.join(func_dir, piece["path"]))
                    frames.append(
                        _trim_frame(df, time_column, piece["start"], piece["end"])
                    )
                    continue

                logger.info(
                    "miss, fetching: %s %s [%d, %d)",
                    func.__qualname__,
                    key_values,
                    piece["start"],
                    piece["end"],
                )
                arguments[start_param] = piece["start"]
                arguments[end_param] = piece["end"]
                df = func(*bound.args, **bound.kwargs)

                # column types must stay the same between gaps
                if isinstance(df, pl.LazyFrame):
                    df = df.collect()

                # drop rows outside the gap (e.g. an inclusive end bar)
                df = _trim_frame(df, time_column, piece["start"], piece["end"])

                df = df.sort(time_column, maintain_order=True)

                # save empty frames too, so a gap with no data is not refetched
                segment_path = os.path.join(
                    *key_values, f"{piece['start']}-{piece['end']}.parquet"
                )
                full_path = os.path.join(func_dir, segment_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                df.write_parquet(full_path)
                frames.append(df)
                segments.append(
                    {
                        "start": piece["start"],
                        "end": piece["end"],
                        "path": segment_path,
                        "ts_event": ts_event,
                    }
                )
                updated = True

            if updated:
                _write_manifest(manifest_path, manifest)

            return pl.concat(frames)

        return wrapper

    return decorator


# -----------------------------------------------------------------------------
# Private API
# -----------------------------------------------------------------------------


def _split_range(segments: list[dict], start: int, end: int) -> list[dict]:
    """Tile ``[start, end)`` with ordered cached and missing pieces.

    A cached piece carries the ``path`` of its segment; a missing piece has
    ``path`` set to ``None``.
    """

    segments = sorted(segments, key=lambda segment: segment["start"], reverse=False)
    cursor = start
    pieces = []
    for segment in segments:
        segment_start, segment_end = segment["start"], segment["end"]
        if segment_end <= start:
            continue
        if segment_start >= end:
            break
        _start, _end = max(segment_start, start), min(segment_end, end)
        if cursor < _start:
            pieces.append({"start": cursor, "end": _start, "path": None})
        pieces.append({"start": _start, "end": _end, "path": segment["path"]})
        cursor = _end
    if cursor < end:
        pieces.append({"start": cursor, "end": end, "path": None})

    return pieces


def _trim_frame(
    df: pl.DataFrame, time_column: str, start: int, end: int
) -> pl.DataFrame:
    """Keep the rows of ``df`` whose time is in ``[start, end)``.

    ``start`` and ``end`` are UNIX nanoseconds. The column can be int64
    nanoseconds or a datetime of any unit.
    """

    times = pl.col(time_column)
    if isinstance(df.schema[time_column], pl.Datetime):
        times = times.dt.epoch("ns")
    return df.filter((times >= start) & (times < end))


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
            json.dump(manifest, f, indent=4, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, manifest_path)
    except BaseException:
        os.unlink(tmp_path)
        raise


# Tests:
# 1. start date is higher than end date
# 2. start or end date is equal to None
# 3. Add a test for merging segments in the manifest

# TODO:
# 1. Save paths support.
# 2. Sha support.
# 3. Check what happens when I request a single date.
# 4. Make sure paths work for both Mac and Windows without damaging atomic write for _write_manifest (don't use os.path)

if __name__ == "__main__":

    def ns(year: int, month: int, day: int) -> int:
        """UTC midnight of a calendar date as UNIX nanoseconds."""
        utc = datetime.timezone.utc
        return int(datetime.datetime(year, month, day, tzinfo=utc).timestamp()) * 10**9

    @range_cache(
        start_param="start",
        end_param="end",
        key_params=["kind", "symbol"],
        time_column="ts",
    )
    def fetch(kind: str, symbol: str, start: int, end: int) -> pl.DataFrame:
        """Mock provider: one row per UTC day in ``[start, end)``."""
        day = 86_400 * 10**9
        ts = list(range(start, end, day))
        return pl.DataFrame(
            {
                "ts": ts,
                "kind": [kind] * len(ts),
                "symbol": [symbol] * len(ts),
                "close": [100.0 + (t // day) % 10 for t in ts],
            }
        )

    # Empty cache: everything is uncovered.
    print(fetch("bar", "aapl", ns(2026, 1, 20), ns(2026, 3, 10)))
    # Fully covered by the segment above.
    print(fetch("bar", "aapl", ns(2026, 2, 20), ns(2026, 3, 10)))
    # Spans the whole cache: gaps on both sides.
    print(fetch("bar", "aapl", ns(2026, 1, 1), ns(2026, 4, 1)))
    # Same symbol under a different kind is cached independently.
    print(fetch("range", "aapl", ns(2026, 1, 20), ns(2026, 3, 10)))
