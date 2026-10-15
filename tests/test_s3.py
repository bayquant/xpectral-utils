# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------

# Standard library imports
from pathlib import Path

# Third-party imports
import pytest
from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError

# First-party imports
from xpectral_utils.s3 import S3Downloader

# -----------------------------------------------------------------------------
# Globals and constants
# -----------------------------------------------------------------------------

_BUCKET = "test-bucket"

# A couple of objects under a shared prefix, plus one elsewhere, to exercise
# prefix filtering and nested key-path preservation on download.
_STORE = {
    "data/2024/01/a.csv.gz": b"a-bytes",
    "data/2024/01/b.csv.gz": b"b-bytes",
    "other/c.csv.gz": b"c-bytes",
}

# -----------------------------------------------------------------------------
# General API
# -----------------------------------------------------------------------------


class _FakeS3:
    """In-memory stand-in for a boto3 S3 client, counting download calls."""

    def __init__(self, store: dict[str, bytes], missing_code: str = "NoSuchKey"):
        self._store = store
        self._missing_code = missing_code
        self.download_calls = []

    def download_file(self, Bucket, Key, Filename):
        self.download_calls.append(Key)
        if Key not in self._store:
            raise ClientError({"Error": {"Code": self._missing_code}}, "GetObject")
        Path(Filename).write_bytes(self._store[Key])

    def get_paginator(self, _name):
        return _FakePaginator(self._store)


class _FakePaginator:
    def __init__(self, store: dict[str, bytes]):
        self._store = store

    def paginate(self, Bucket, Prefix):
        contents = [{"Key": key} for key in self._store if key.startswith(Prefix)]
        yield {"Contents": contents}


def _make(tmp_path: Path) -> S3Downloader:
    dl = S3Downloader(bucket=_BUCKET, dest_dir=tmp_path)
    dl._client = _FakeS3(dict(_STORE))
    return dl


# --- download ----------------------------------------------------------------


def test_download_skips_existing_and_missing(tmp_path):
    dl = _make(tmp_path)

    # Pre-place the first object so only the second is fetched.
    first = tmp_path / "data/2024/01/a.csv.gz"
    first.parent.mkdir(parents=True)
    first.write_bytes(_STORE["data/2024/01/a.csv.gz"])

    missing = "data/2024/01/missing.csv.gz"
    paths = dl.download(list(_STORE) + [missing])

    # a.csv.gz is skipped (already local); missing.csv.gz is attempted then 404s.
    assert dl._client.download_calls == [
        "data/2024/01/b.csv.gz",
        "other/c.csv.gz",
        missing,
    ]
    assert {p.name for p in paths} == {"a.csv.gz", "b.csv.gz", "c.csv.gz"}


def test_download_overwrite_refetches_existing(tmp_path):
    dl = _make(tmp_path)
    key = "data/2024/01/a.csv.gz"

    # Pre-place a stale file under the key.
    stale = tmp_path / key
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale")

    # Default: skipped, stale bytes kept, no network call.
    dl.download([key])
    assert dl._client.download_calls == []
    assert stale.read_bytes() == b"stale"

    # overwrite=True: re-fetched and replaced with the store's bytes.
    dl.download([key], overwrite=True)
    assert dl._client.download_calls == [key]
    assert stale.read_bytes() == _STORE[key]


def test_download_treats_403_as_missing(tmp_path):
    # Download-only credentials get 403/AccessDenied for absent keys, not 404;
    # those must be skipped like a normal miss, not raised.
    dl = S3Downloader(bucket=_BUCKET, dest_dir=tmp_path)
    dl._client = _FakeS3({}, missing_code="403")
    assert dl.download(["data/2024/01/a.csv.gz"]) == []


def test_download_preserves_key_path(tmp_path):
    dl = _make(tmp_path)
    paths = dl.download(["data/2024/01/a.csv.gz"])
    assert paths == [tmp_path / "data/2024/01/a.csv.gz"]
    assert paths[0].read_bytes() == _STORE["data/2024/01/a.csv.gz"]


def test_download_dest_dir_overrides_root(tmp_path):
    dl = _make(tmp_path)
    other = tmp_path / "elsewhere"
    paths = dl.download(["other/c.csv.gz"], dest_dir=other)
    assert paths == [other / "other/c.csv.gz"]


def test_download_raises_on_connection_failure(tmp_path):
    # A genuine connectivity failure (DNS/timeout/etc.) is a BotoCoreError,
    # not a ClientError -- it must not be swallowed like a missing object.
    class _UnreachableS3:
        def download_file(self, Bucket, Key, Filename):
            raise BotoCoreError()

    dl = S3Downloader(bucket=_BUCKET, dest_dir=tmp_path)
    dl._client = _UnreachableS3()

    with pytest.raises(BotoCoreError):
        dl.download(["data/2024/01/a.csv.gz"])


# --- list --------------------------------------------------------------------


def test_list_filters_by_prefix(tmp_path):
    dl = _make(tmp_path)
    keys = dl.list_keys("data/2024/01")
    assert sorted(keys) == ["data/2024/01/a.csv.gz", "data/2024/01/b.csv.gz"]
