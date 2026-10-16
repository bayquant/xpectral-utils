# Dates rules

Design notes for `xpectral_utils/dates.py`. The module is a thin, dependency-free
layer that turns whatever a caller has into one of two canonical forms, so the
rest of the code never has to guess what a date value means.

## Core principle

Dates and instants are different things, so they get different types and
different validators.

| Concept | Canonical form | Validator |
|---|---|---|
| Calendar day (daily data, expiries, trading dates) | `datetime.date` | `to_date` |
| Instant (intraday data, event times) | aware UTC `datetime`, or integer UNIX nanoseconds | `to_datetime`, `to_unix_ns` |

Lenient on formats within a mode, strict across modes. Normalize once at the
boundary, then only the canonical form exists downstream.

## Rules

1. **UTC everywhere internally.** Instants are stored and passed as aware UTC
   `datetime` or integer nanoseconds since the UNIX epoch. Local time is a
   display concern only.
2. **Never guess a timezone.** Naive datetimes and naive ISO strings raise
   `ValueError`. The caller attaches a zone explicitly with `localize`.
3. **A bare `date` is not an instant.** `to_datetime` and `to_unix_ns` raise
   `TypeError` for it. Silently mapping a date to midnight UTC would cut a US
   session in two.
4. **No `datetime` subclasses.** `pd.Timestamp` raises `TypeError`, because
   converting it through `datetime` silently drops nanoseconds. See
   [Why `pd.Timestamp` is rejected](#why-pdtimestamp-is-rejected).
5. **A `datetime` is not a calendar day.** `to_date` raises `TypeError` for it.
6. **Integers are nanoseconds, and are range-checked.** Values outside
   `[1e17, 2**63 - 1]` raise `ValueError`. Seconds, milliseconds and
   microseconds for any modern date fall below the lower bound, so a unit
   mistake fails loudly instead of becoming a 1970 timestamp. Side effect:
   timestamps before 1973-03-03 cannot be passed as integers.
7. **Integer math is exact.** Name variables with a `_ns` suffix and build
   durations from the `NS_PER_*` constants. Never go through float seconds,
   which lose precision at current epoch magnitudes.
8. **Ranges are half-open, `[start, end)`.** `start` inclusive, `end` exclusive,
   so adjacent ranges tile without overlap or gaps.

## API

| Name | Purpose |
|---|---|
| `to_date(str \| date)` | Strict calendar day. |
| `to_datetime(str \| datetime)` | Aware instant, converted to UTC. |
| `to_unix_ns(int \| str \| datetime)` | Integer UTC nanoseconds. |
| `from_unix_ns(int)` | Aware UTC `datetime`, truncated to microseconds. |
| `localize(naive, tz)` | Attach an IANA zone to a naive wall-clock time. |
| `NS_PER_SECOND`, `NS_PER_MINUTE`, `NS_PER_HOUR`, `NS_PER_DAY` | Unit constants. |

## Recipes

Ten o'clock New York time as an instant:

```python
from datetime import datetime

from xpectral_utils.dates import localize, to_unix_ns

start_ns = to_unix_ns(localize(datetime(2024, 1, 2, 10), "America/New_York"))
```

Ten seconds before an instant:

```python
from xpectral_utils.dates import NS_PER_SECOND

earlier_ns = end_ns - 10 * NS_PER_SECOND
```

One week of elapsed time before an instant (exactly 7 x 24 hours in UTC):

```python
from xpectral_utils.dates import NS_PER_DAY

week_ago_ns = end_ns - 7 * NS_PER_DAY
```

## Which kind of "a week ago"

| Meaning | Tool |
|---|---|
| Fixed elapsed time (seconds to weeks) | integer ns and `NS_PER_*` |
| Same local wall-clock time | convert with `zoneinfo`, shift, convert back (DST changes the elapsed time) |
| Calendar days on a `date` | `date - timedelta(days=n)` |
| Trading days | an exchange calendar (not in this module) |
| Months or years | dates only; they are not fixed lengths |

## Precision

`datetime` resolves to microseconds. `to_unix_ns` from a string or `datetime`
therefore always ends in three zeros, and `from_unix_ns` truncates. Keep the
integer when the last three digits matter. Do arithmetic on integers, not on
round-tripped `datetime` values.

## Why `pd.Timestamp` is rejected

`pd.Timestamp` subclasses `datetime`, so it would pass a plain `isinstance`
check, but it can hold nanoseconds and `datetime` cannot. Any conversion that
goes through `datetime` arithmetic (`astimezone`, `timedelta`) quietly drops the
last three digits:

```python
ts = pd.Timestamp("2024-01-02 15:00:00.123456789", tz="UTC")
ts.value                # 1704207600123456789  (true value)
# via datetime math:    # 1704207600123456000  (nanoseconds lost, no error)
```

For tick data that is exactly the digits that order events within a
microsecond, so a silent truncation is worse than an error.

Both `to_datetime` and `to_unix_ns` therefore accept only the exact stdlib
`datetime` type (`type(value) is datetime`), which rejects subclasses without
importing pandas. The error message names the fix.

| Starting from | Do this |
|---|---|
| `pd.Timestamp` | `to_unix_ns(ts.value)` (`.value` is always UTC nanoseconds, tz-aware or not) |
| pandas column | `df["ts"].astype("int64")` (or `.dt.tz_convert("UTC").astype("int64")`) |
| `numpy.datetime64[ns]` | `int(value.astype("int64"))`; it is not a `datetime`, so it raises `TypeError` already |
| polars column | `s.dt.epoch("ns")`, taken on the column before extracting scalars |

### Polars

Polars does not reproduce the `pd.Timestamp` problem inside this module, because
a polars scalar (`series[0]`) is already a plain stdlib `datetime`. The loss
happens one step earlier: a `pl.Datetime("ns")` value is truncated to
microseconds at the moment it is extracted to Python.

```python
s = pl.Series([1704207600123456789], dtype=pl.Datetime("ns", "UTC"))
s[0]                    # datetime(2024, 1, 2, 15, 0, 0, 123456, tzinfo=UTC)  (ns gone)
s.dt.epoch("ns")[0]     # 1704207600123456789  (exact)
```

Nothing here can detect that, since the value arrives as a normal `datetime`.
The rule is to extract integer nanoseconds with `dt.epoch("ns")` while the data
is still in the frame, then pass the integers to `to_unix_ns`.

## DST caveats in `localize`

- **Ambiguous time** (the repeated hour when clocks fall back): resolves to the
  first occurrence (`fold=0`) without raising.
- **Non-existent time** (the skipped hour when clocks spring forward): not
  rejected; an offset is picked and the result does not match a real reading.

Regular US equity hours (09:30 to 16:00) are far from the 02:00 transitions and
are unaffected. Futures and overnight sessions on the two transition Sundays are
where this can bite. Raising in both cases is the stricter option under
consideration.

## Why not follow Databento exactly

Databento's client is a good model for UTC nanoseconds, half-open ranges, and
flexible input types, but a few of its choices are deliberately not copied:

- It treats naive input as UTC silently. Here it raises.
- It passes integers through with no checking. Here they are range-checked.
- It maps a `date` to midnight UTC for instants. Here that raises.

## Out of scope for now

- Shift helpers (`shift_local`, `shift_trading_days`).
- Exchange calendars and session boundaries for daily data.
- An interval type enforcing `[start, end)` with `start < end`.
- Daily-vs-intraday dispatch, which belongs in the fetching function.
