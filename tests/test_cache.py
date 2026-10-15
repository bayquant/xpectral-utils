# ----------------------------------------------------------------------------
# Imports
# ----------------------------------------------------------------------------

# Standard library imports
import time
from pathlib import Path

# First-party imports
from xpectral_utils.cache import disk_cache

# ----------------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------------


def test_caches_results_by_arguments(tmp_path):
    calls = []

    @disk_cache("square", cache_dir=tmp_path)
    def square(x):
        calls.append(x)
        return x * x

    assert square(3) == 9
    assert square(3) == 9
    assert square(4) == 16
    assert calls == [3, 4]


def test_persists_across_decorations(tmp_path):
    calls = []

    def build():
        @disk_cache("double", cache_dir=tmp_path)
        def double(x):
            calls.append(x)
            return 2 * x

        return double

    assert build()(5) == 10
    assert build()(5) == 10
    assert calls == [5]


def test_each_function_gets_its_own_subdirectory(tmp_path):
    @disk_cache("first", cache_dir=tmp_path)
    def first(x):
        return x

    @disk_cache("second", cache_dir=tmp_path)
    def second(x):
        return x

    first(1)
    second(1)

    assert (tmp_path / "first").is_dir()
    assert (tmp_path / "second").is_dir()


def test_name_defaults_to_the_qualified_name(tmp_path):
    @disk_cache(cache_dir=tmp_path)
    def helper(x):
        return x

    assert (tmp_path / helper.__wrapped__.__qualname__).is_dir()


def test_expired_entries_are_recomputed(tmp_path):
    calls = []

    @disk_cache("ttl", expire=0.05, cache_dir=tmp_path)
    def value(x):
        calls.append(x)
        return x

    value(1)
    time.sleep(0.1)
    value(1)

    assert calls == [1, 1]


def test_typed_separates_int_from_float(tmp_path):
    calls = []

    @disk_cache("typed", typed=True, cache_dir=tmp_path)
    def echo(x):
        calls.append(type(x))
        return x

    echo(1)
    echo(1.0)

    assert calls == [int, float]


def test_exposes_the_backing_cache(tmp_path):
    @disk_cache("exposed", cache_dir=tmp_path)
    def value(x):
        return x

    value(1)
    assert len(value.cache) == 1

    value.cache.clear()
    assert len(value.cache) == 0


def test_env_var_sets_the_default_root(tmp_path, monkeypatch):
    monkeypatch.setenv("XPECTRAL_CACHE_DIR", str(tmp_path))

    @disk_cache("from-env")
    def value(x):
        return x

    value(1)

    assert (tmp_path / "from-env").is_dir()


def test_explicit_cache_dir_overrides_the_env_var(tmp_path, monkeypatch):
    env_dir = tmp_path / "env"
    arg_dir = tmp_path / "arg"
    monkeypatch.setenv("XPECTRAL_CACHE_DIR", str(env_dir))

    @disk_cache("explicit", cache_dir=arg_dir)
    def value(x):
        return x

    value(1)

    assert (arg_dir / "explicit").is_dir()
    assert not Path(env_dir).exists()
