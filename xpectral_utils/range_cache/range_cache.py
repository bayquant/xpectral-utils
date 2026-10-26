"""On-disk range cache (install ``xpectral-utils[cache]``)."""

# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------

# Standard library imports
import datetime
import json

# Third-party imports

# -----------------------------------------------------------------------------
# Globals and constants
# -----------------------------------------------------------------------------

__all__ = ["range_cache"]

_RANGE_CACHE_PATH = "./xpectral_utils/range_cache/manifest.json"

# -----------------------------------------------------------------------------
# General API
# -----------------------------------------------------------------------------


def range_cache(
    kind: str, symbol: str, start: datetime.date, end: datetime.date
) -> dict:

    # Range is inclusive of start but not end to avoid overlap with next range.
    if start >= end:
        raise ValueError("Start date must be less than end date.")

    with open(_RANGE_CACHE_PATH) as f:
        manifest = json.load(f)

    segments = manifest.setdefault(kind, {}).setdefault(symbol, [])
    if not segments:
        # fetch data from provider.
        segments.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "ts_event": datetime.datetime.now().isoformat(),
                "sha": "dummy_sha",
            }
        )
        print("No range cache found for kind: {}, symbol: {}".format(kind, symbol))

        with open(_RANGE_CACHE_PATH, "w") as f:
            json.dump(manifest, f, indent=4, sort_keys=True)

    covered, uncovered = _split_coverage(segments, start, end)
    # fetch data from provider.
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    segments.extend(
        {
            "start": gap["start"].isoformat(),
            "end": gap["end"].isoformat(),
            "ts_event": now,
            "sha": "dummy_sha",
        }
        for gap in uncovered
    )
    with open(_RANGE_CACHE_PATH, "w") as f:
        json.dump(manifest, f, indent=4, sort_keys=True)

    return covered, uncovered


# -----------------------------------------------------------------------------
# Private API
# -----------------------------------------------------------------------------


def _split_coverage(
    segments: list[dict], start: datetime.date, end: datetime.date
) -> tuple[list[dict], list[dict]]:
    """Split ``[start, end)`` into cached and missing date ranges."""

    segments = sorted(segments, key=lambda segment: segment["start"], reverse=False)
    cursor = start
    covered, uncovered = [], []
    for segment in segments:
        segment_start = datetime.date.fromisoformat(segment["start"])
        segment_end = datetime.date.fromisoformat(segment["end"])
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


# Tests:
# 1. start date is higher than end date
# 2. start or end date is equal to None

if __name__ == "__main__":
    print(
        range_cache(
            kind="bar",
            symbol="aapl",
            start=datetime.date(2026, 1, 20),
            end=datetime.date(2026, 3, 10),
        )
    )
    print(
        range_cache(
            kind="bar",
            symbol="aapl",
            start=datetime.date(2026, 2, 20),
            end=datetime.date(2026, 3, 10),
        )
    )
    range_cache(
        kind="bar",
        symbol="ibm",
        start=datetime.date(2023, 1, 1),
        end=datetime.date(2023, 1, 10),
    )
    range_cache(
        kind="range",
        symbol="ibm",
        start=datetime.date(2023, 1, 1),
        end=datetime.date(2023, 1, 10),
    )
