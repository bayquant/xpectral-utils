"""On-disk function memoization built on diskcache (install ``xpectral-utils[cache]``)."""

# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------

# Standard library imports
import os
from collections.abc import Callable
from pathlib import Path
from typing import Literal

# Third-party imports
from diskcache import Cache

# -----------------------------------------------------------------------------
# Globals and constants
# -----------------------------------------------------------------------------

__all__ = ["EvictionPolicy", "disk_cache"]

# The eviction policies diskcache accepts once ``size_limit`` is reached.
EvictionPolicy = Literal[
    "none",
    "least-recently-stored",
    "least-recently-used",
    "least-frequently-used",
]

# Root under which every function gets its own cache subdirectory. Overridable
# per call, or globally via the XPECTRAL_CACHE_DIR environment variable.
_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "xpectral"

# Default per-function size cap before least-recently-used eviction kicks in.
_SIZE_LIMIT = 2 * 2**30  # 2 GiB

# -----------------------------------------------------------------------------
# General API
# -----------------------------------------------------------------------------


def disk_cache(
    name: str | None = None,
    *,
    expire: float | None = None,
    cache_dir: str | os.PathLike | None = None,
    size_limit: int = _SIZE_LIMIT,
    eviction_policy: EvictionPolicy = "least-recently-used",
    typed: bool = False,
) -> Callable:
    """Cache a function's return values on disk, keyed by its arguments.

    Each decorated function gets its own :class:`diskcache.Cache` backed by its
    own subdirectory -- there is no shared global cache instance. Values are
    pickled, so the function must return picklable objects and take
    picklable/hashable arguments.

    Args:
        name: Subdirectory name for this function's cache. Defaults to the
            function's qualified name.
        expire: Time-to-live in seconds. ``None`` caches indefinitely.
        cache_dir: Root directory for the cache. Defaults to the
            ``XPECTRAL_CACHE_DIR`` environment variable, else
            ``~/.cache/xpectral``.
        size_limit: Byte cap for this function's cache before entries are evicted
            per ``eviction_policy``.
        eviction_policy: How entries are chosen for eviction once ``size_limit``
            is reached. One of ``"least-recently-stored"``,
            ``"least-recently-used"``, ``"least-frequently-used"``, or ``"none"``
            (no automatic eviction).
        typed: When ``True``, arguments of different types are cached separately
            (e.g. ``1`` and ``1.0``).

    Returns:
        A decorator that wraps the target function with on-disk memoization.
        The wrapped function exposes its backing store as ``func.cache`` (a
        :class:`diskcache.Cache`), so callers can ``func.cache.clear()`` or
        check ``len(func.cache)``.
    """

    def decorator(func: Callable) -> Callable:
        directory = _resolve_dir(cache_dir) / (name or func.__qualname__)
        cache = Cache(
            directory=str(directory),
            size_limit=size_limit,
            eviction_policy=eviction_policy,
        )
        memoized = cache.memoize(expire=expire, typed=typed)(func)
        # Expose the backing Cache so callers can inspect or clear it, e.g.
        # ``func.cache.clear()`` or ``len(func.cache)``.
        memoized.cache = cache
        return memoized

    return decorator


# -----------------------------------------------------------------------------
# Private API
# -----------------------------------------------------------------------------


def _resolve_dir(cache_dir: str | os.PathLike | None) -> Path:
    """Resolve the cache root: explicit arg, else env var, else default."""
    if cache_dir is not None:
        return Path(cache_dir)
    env = os.getenv("XPECTRAL_CACHE_DIR")
    return Path(env) if env else _DEFAULT_CACHE_DIR
