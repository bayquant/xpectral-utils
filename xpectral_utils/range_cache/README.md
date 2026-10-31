# Range Cache

A small on-disk index that answers one question: for a requested time range, which parts do we already have, and which parts must be fetched?

The cache stores no data itself. It stores a manifest of which time ranges have been fetched for each `(kind, symbol)` pair, so callers only download the gaps.

## Theory

### Half-open intervals

Every range is half-open, `[start, end)`, in UNIX nanoseconds (UTC). Integers only, no floats or `datetime` at this layer.

Half-open ranges tile the time axis without overlap or gaps: `[a, b)` and `[b, c)` are adjacent, share no instant, and together cover `[a, c)`. A request starting exactly where a cached segment ends therefore needs no special case. The cache never double-counts the boundary nanosecond.

A request with `start >= end` is empty or inverted and raises `ValueError`.

### Coverage as interval subtraction

Given a request `R = [start, end)` and cached segments `S_1, ..., S_n`, the cache computes:

- **covered**: `R ∩ (S_1 ∪ ... ∪ S_n)`, the parts of `R` already cached.
- **uncovered**: `R \ (S_1 ∪ ... ∪ S_n)`, the gaps that must be fetched.

The two lists partition `R`: together they tile it exactly, in order, with no overlap.

### Sweep algorithm

`_split_coverage` sorts segments by start and sweeps left to right with a cursor that begins at `start`:

1. Skip segments that end at or before `start` (entirely left of the request).
2. Stop at the first segment that starts at or after `end` (entirely right, and all later ones too since sorted).
3. Clip the segment to the request: `[max(seg_start, start), min(seg_end, end))`.
4. If the cursor is behind the clipped start, the space between is a gap: emit it as uncovered.
5. Emit the clipped segment as covered and advance the cursor to its end.
6. After the loop, if the cursor is short of `end`, the tail is a gap.

Cost is `O(n log n)` for the sort plus `O(n)` for the sweep, where `n` is the number of segments for that `(kind, symbol)`.

The sweep assumes the stored segments are disjoint. If two segments overlapped, the cursor logic would emit overlapping covered ranges. See [Known limitations](#known-limitations).

## Architecture

```
caller
  │  range_cache(kind, symbol, start, end)
  ▼
range_cache()
  1. validate start < end
  2. load manifest.json
  3. look up manifest[kind][symbol] (created empty if absent)
  4. _split_coverage(segments, start, end) -> (covered, uncovered)
  5. record each uncovered gap as a new segment
  6. _write_manifest()  (atomic)
  7. return (covered, uncovered)
```

### Files

| File | Purpose |
|---|---|
| `range_cache.py` | Public `range_cache` function and private helpers. |
| `manifest.json` | The index. Created and rewritten by the cache. |

### Manifest schema

Two-level mapping, `kind` then `symbol`, to a list of segments:

```json
{
    "bar": {
        "aapl": [
            {
                "start": 1768867200000000000,
                "end": 1773100800000000000,
                "ts_event": 1761862800000000000,
                "path": "bar/aapl/1768867200000000000-1773100800000000000"
            }
        ]
    }
}
```

| Field | Meaning |
|---|---|
| `start`, `end` | Half-open range `[start, end)` in UNIX nanoseconds (UTC). |
| `ts_event` | Wall-clock time (ns) when the segment was recorded. |
| `path` | Location of the segment's data file, relative to the cache root. One file per segment, named `{kind}/{symbol}/{start}-{end}`. No extension yet, since the file format is undecided. |

A content hash (`sha`) may be added later for integrity checks or provider-revision detection.

`kind` namespaces independent datasets (for example `"bar"` and `"range"`). The same symbol under two kinds is cached independently.

### Atomic writes

`_write_manifest` writes to a temp file in the same directory as the manifest, flushes and `fsync`s it, then `os.replace`s it over the target. On POSIX the rename is atomic, so a reader or a crash never observes a half-written manifest. The temp file must live on the same filesystem as the target for this to hold, hence `dir=os.path.dirname(...)`. On any failure the temp file is removed and the exception re-raised.

## Usage

```python
from xpectral_utils.range_cache.range_cache import range_cache

covered, uncovered = range_cache("bar", "aapl", start_ns, end_ns)
```

Both return values are lists of `{"start": int, "end": int}` dicts in ascending order.

Example: segment `[10, 20)` cached, request `[5, 25)`:

```
covered   = [{"start": 10, "end": 20}]
uncovered = [{"start": 5, "end": 10}, {"start": 20, "end": 25}]
```

`range_cache.py` has a `__main__` block that walks through the main cases: empty cache, full hit, right gap, left gap, gaps on both sides, a hole between two segments, independent kinds, adjacency, and invalid input. Run it from the repository root.

## Current state and known limitations

The cache is a work in progress. Things to know before relying on it:

- **Fetch is a stub.** Uncovered gaps are recorded in the manifest as if they had been fetched, with a `path` that nothing writes to yet. No provider call happens, so today a call marks the gaps as cached before any data exists.
- **No segment merging.** Adjacent or overlapping segments are appended as-is, never coalesced. Gaps are computed against the current segments so new ones never overlap existing ones, but the list grows with many small adjacent entries, and the sweep's disjointness assumption relies on that.
- **No concurrency control.** The read-modify-write on the manifest is atomic only for the final replace. Two processes calling at once can both read the same state, and the last writer wins, losing the other's segments.
- **Relative manifest path.** `_RANGE_CACHE_PATH` is relative to the current working directory, so the cache only works when run from the repository root.
- **Return annotation.** `range_cache` is annotated `-> dict` but returns a `(covered, uncovered)` tuple.
- **No logging** of cache hits and misses yet (listed in the file's TODO).

## Planned tests

- `start >= end` raises `ValueError`.
- `None` for `start` or `end`.
- Merging of adjacent segments in the manifest.
