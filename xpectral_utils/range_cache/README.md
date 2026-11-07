# Range Cache

A decorator factory that gives a function an on-disk range cache. For a requested time range, it works out which parts are already cached and which parts must be fetched, so only the gaps are fetched.

The cache is a manifest plus one data file per cached segment. The manifest is a JSON index of which time ranges have been fetched for each combination of key values. Each decorated function gets its own directory and manifest, so different functions never collide. The data is a polars `DataFrame`, stored as parquet.

## Theory

### Half-open intervals

Every range is half-open, `[start, end)`, in UNIX nanoseconds (UTC). Integers only, no floats or `datetime` at this layer.

Half-open ranges tile the time axis without overlap or gaps: `[a, b)` and `[b, c)` are adjacent, share no instant, and together cover `[a, c)`. A request starting exactly where a cached segment ends therefore needs no special case. The cache never double-counts the boundary nanosecond.

A request with `start >= end` is empty or inverted and raises `InvalidRangeError`.

### Coverage as a tiling

Given a request `R = [start, end)` and cached segments `S_1, ..., S_n`, the cache splits `R` into an ordered list of pieces:

- **cached piece**: a part of `R` inside some `S_i`, clipped to `R`. It carries the `path` of that segment's data file.
- **missing piece**: a gap of `R` outside every `S_i`, which must be fetched. Its `path` is `None`.

The pieces tile `R` exactly: in order, with no overlap and no gaps. Because they are already in time order, one loop over them can read the cached parts and fetch the missing parts.

### Sweep algorithm

`_split_range` sorts segments by start and sweeps left to right with a cursor that begins at `start`:

1. Skip segments that end at or before `start` (entirely left of the request).
2. Stop at the first segment that starts at or after `end` (entirely right, and all later ones too since sorted).
3. Clip the segment to the request: `[max(seg_start, start), min(seg_end, end))`.
4. If the cursor is behind the clipped start, the space between is a gap: emit it as a missing piece.
5. Emit the clipped segment as a cached piece and advance the cursor to its end.
6. After the loop, if the cursor is short of `end`, the tail is a gap.

Cost is `O(n log n)` for the sort plus `O(n)` for the sweep, where `n` is the number of segments for that key.

The sweep assumes the stored segments are disjoint. If two segments overlapped, the cursor logic would emit overlapping cached pieces. See [Current state and known limitations](#current-state-and-known-limitations).

## Architecture

```
@range_cache(start_param=..., end_param=..., key_params=[...], time_column=...)
def fetch(...): ...
```

`range_cache` is a decorator factory: it returns a decorator configured with the four settings, and the decorator returns the wrapper that replaces the function.

```
at decoration time (once)
  1. check that start_param, end_param and key_params are parameters of the function
  2. func_dir      = <cache root>/range_cache/<module>.<qualname>
  3. manifest_path = func_dir/manifest.json

on every call to the wrapper
  1. bind the arguments to the function's signature, applying defaults
  2. key_values = str() of the key_params arguments; start, end from the range arguments
  3. validate start < end
  4. load the manifest and walk its tree down to the key_values (created empty if absent)
  5. _split_range(segments, start, end) -> pieces
  6. for each piece:
       cached  -> read its parquet file and trim it to the piece
       missing -> call the function for the piece, trim the result to the piece,
                  write it as a parquet file and record the segment
  7. _write_manifest() if any segment was added (atomic)
  8. pl.concat() the pieces, already in time order, and return the DataFrame
```

Trimming keeps the rows whose `time_column` is in the piece's `[start, end)`. A cached segment file can extend past the request, and a provider can return rows outside the gap it was asked for (for example an inclusive end bar), so both are trimmed. The time column can be int64 nanoseconds or a `Datetime` of any unit and time zone.

### Files

All paths are under the cache root, `DEFAULT_CACHE_DIR` from [config.py](../config.py), which is `~/.cache/xpectral`. The range cache keeps everything in its `range_cache` subfolder.

| File | Purpose |
|---|---|
| `range_cache.py` | The `range_cache` decorator factory and private helpers. |
| `<module>.<qualname>/manifest.json` | One index per decorated function. Created and rewritten by the cache. |
| `<module>.<qualname>/{key values}/*.parquet` | Segment data files, one folder level per key value, created next to the manifest. |

### Manifest schema

A tree with one level per entry of `key_params`, in order, ending in a list of segments. For `key_params=["kind", "symbol"]`:

```json
{
    "bar": {
        "aapl": [
            {
                "start": 1768867200000000000,
                "end": 1773100800000000000,
                "path": "bar/aapl/1768867200000000000-1773100800000000000.parquet",
                "ts_event": 1761862800000000000
            }
        ]
    }
}
```

| Field | Meaning |
|---|---|
| `start`, `end` | Half-open range `[start, end)` in UNIX nanoseconds (UTC). |
| `ts_event` | Wall-clock time (ns) when the segment was recorded. |
| `path` | Location of the segment's data file, relative to the function's directory. One file per segment, named `{key values}/{start}-{end}.parquet`. A gap with no data is saved as an empty parquet file, so it is not fetched again. |

A content hash (`sha`) may be added later for integrity checks or provider-revision detection.

The key values namespace independent datasets. The same symbol under two different `kind` values is cached independently.

### Atomic writes

`_write_manifest` writes to a temp file in the same directory as the manifest, flushes and `fsync`s it, then `os.replace`s it over the target. On POSIX the rename is atomic, so a reader or a crash never observes a half-written manifest. The temp file must live on the same filesystem as the target for this to hold, hence `dir=os.path.dirname(...)`. On any failure the temp file is removed and the exception re-raised.

The manifest is saved right after the segments are recorded and before the data is combined. Combining can fail, and the fetched segments are already on disk by then. A call that adds no segments does not rewrite the manifest.

## Usage

```python
import polars as pl

from xpectral_utils.range_cache.range_cache import range_cache


@range_cache(
    start_param="start",
    end_param="end",
    key_params=["kind", "symbol"],
    time_column="ts",
)
def fetch(kind: str, symbol: str, start: int, end: int) -> pl.DataFrame: ...


fetch("bar", "aapl", start_ns, end_ns)
```

| Setting | Meaning |
|---|---|
| `start_param` | Name of the parameter holding the range start (UNIX ns, UTC). |
| `end_param` | Name of the parameter holding the exclusive range end. |
| `key_params` | Names of the parameters whose values form the manifest tree, in order. |
| `time_column` | Name of the column of the returned DataFrame that holds each row's time. Used to trim rows to the requested range. |

The first three are parameter names, not values. A function whose parameters are called `begin` and `finish` would use `start_param="begin"` and `end_param="finish"`. Decorating a function that lacks one of the named parameters raises `DecoratorConfigError` immediately.

### Data contract

The decorated function must return a polars `DataFrame` or `LazyFrame` with a `time_column`. A `LazyFrame` is collected when fetched. The cache always returns an eager `DataFrame` with the same columns, sorted by `time_column`.

- **Order within a time is kept.** Each fetched piece is sorted by `time_column` with a stable sort, so rows that share a timestamp stay in the order the provider returned them.

- **Column types must stay the same between calls.** Types that polars infers from the values can change: `[100, 101]` is `Int64` and `[100.0, 101.0]` is `Float64`, and a day with no data gives `Null` columns. Pieces with different types cannot be concatenated, and a segment already saved stays in the cache. Build the frame with an explicit schema, for example `pl.DataFrame(rows, schema={"ts": pl.Int64, "close": pl.Float64})`.
- **Column order must stay the same too.** `pl.concat` raises a `ShapeError` otherwise.
- **An empty result is fine.** Empty frames, including `Null`-typed ones, are cached and combine with real data.
- **`Object` columns cannot be stored** in parquet.

Example: segment `[10, 20)` cached, request `[5, 25)`:

```python
[
    {"start": 5, "end": 10, "path": None},
    {"start": 10, "end": 20, "path": "<key values>/10-20.parquet"},
    {"start": 20, "end": 25, "path": None},
]
```

`range_cache.py` has a `__main__` block that decorates a mock provider returning polars data and walks through the main cases: empty cache, full hit, gaps on both sides, and independent key values. It writes to the same cache folder as real use, under `~/.cache/xpectral/range_cache/__main__.fetch/`, so delete that folder to start from an empty cache.

## Current state and known limitations

The cache is a work in progress. Things to know before relying on it:

- **No schema check.** The column types and order a provider returns are not validated (see [Data contract](#data-contract)). A mismatch fails when the pieces are combined, after the new segment is already saved. A declared schema, checked before each segment is written, is planned.
- **Cached "nothing found" is final.** An empty gap is saved as an empty segment, so data a provider adds later for that range is not picked up.
- **Polars only.** The function must return a polars `DataFrame` or `LazyFrame`. Other types (pandas, Arrow tables) are not converted.
- **No segment merging.** Adjacent segments are never coalesced, so the list grows with many small entries. Consolidation is planned as a separate step after the manifest is saved.
- **No concurrency control.** The read-modify-write on the manifest is atomic only for the final replace. Two processes calling at once can both read the same state, and the last writer wins, losing the other's segments.
- **Fixed cache root.** The root is `DEFAULT_CACHE_DIR` and cannot be changed per call or by an environment variable yet.
- **Key values become folder names.** They are converted with `str()`, so a value containing a path separator would break the layout.
- **Function directory names.** The directory is `<module>.<qualname>`. A script run directly has the module `__main__`, and a nested function includes `<locals>` in its name.
- **No logging** of cache hits and misses yet (listed in the file's TODO).

## Planned tests

- `start >= end` raises `InvalidRangeError`.
- `None` for `start` or `end`.
- Decorating a function with a wrong parameter name raises `DecoratorConfigError`.
- Cache miss, hit and partial hit call the function only for the gaps.
- Rows outside a requested gap are trimmed.
- Empty gaps are cached and not fetched again, and combine with real data.
- Merging of adjacent segments in the manifest.
