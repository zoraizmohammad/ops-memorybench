"""Tests for the content addressed blob store."""

from __future__ import annotations

import pytest

from ombench.ids import sha256_hex
from ombench.storage.blobstore import (
    BlobIntegrityError,
    BlobNotFoundError,
    BlobStore,
    make_blob_uri,
    parse_blob_uri,
)


@pytest.fixture
def store(tmp_path):
    return BlobStore(tmp_path / "blobs")


def test_put_and_get_bytes(store):
    digest = store.put_bytes(b"hello")
    assert digest == sha256_hex(b"hello")
    assert store.get_bytes(digest) == b"hello"


def test_put_and_get_text(store):
    digest = store.put_text("hello world")
    assert store.get_text(digest) == "hello world"


def test_put_and_get_json_round_trip(store):
    payload = {"b": 1, "a": [1, 2, 3]}
    digest = store.put_json(payload)
    assert store.get_json(digest) == payload


def test_json_is_content_addressed_dedupe(store):
    # Two semantically equal payloads must address the same blob.
    d1 = store.put_json({"a": 1, "b": 2})
    d2 = store.put_json({"b": 2, "a": 1})
    assert d1 == d2
    assert len(list(store.iter_digests())) == 1


def test_distinct_content_distinct_hash(store):
    d1 = store.put_json({"a": 1})
    d2 = store.put_json({"a": 2})
    assert d1 != d2
    assert len(list(store.iter_digests())) == 2


def test_get_via_blob_uri(store):
    digest = store.put_text("x")
    uri = make_blob_uri(digest)
    assert store.get_text(uri) == "x"


def test_blob_uri_round_trip():
    digest = sha256_hex("y")
    assert parse_blob_uri(make_blob_uri(digest)) == digest
    # A bare hash is also accepted.
    assert parse_blob_uri(digest) == digest


def test_parse_blob_uri_rejects_garbage():
    with pytest.raises(ValueError):
        parse_blob_uri("blob://not-a-hash")


def test_missing_blob_raises(store):
    with pytest.raises(BlobNotFoundError):
        store.get_bytes(sha256_hex("absent"))


def test_exists(store):
    digest = store.put_text("present")
    assert store.exists(digest)
    assert store.exists(make_blob_uri(digest))
    assert not store.exists(sha256_hex("absent"))
    assert not store.exists("garbage")


def test_size(store):
    digest = store.put_bytes(b"12345")
    assert store.size(digest) == 5


def test_integrity_check_detects_corruption(store):
    digest = store.put_text("original")
    # Corrupt the stored bytes directly on disk.
    path = store._path_for(digest)
    path.write_bytes(b"tampered")
    with pytest.raises(BlobIntegrityError):
        store.get_bytes(digest)
    assert store.verify_all() == [digest]


def test_fanout_layout(store):
    digest = store.put_text("layout")
    path = store._path_for(digest)
    assert path.parent.name == digest[:2]
    assert path.name == digest[2:]


def test_idempotent_write(store):
    d1 = store.put_bytes(b"same")
    d2 = store.put_bytes(b"same")
    assert d1 == d2
    assert len(list(store.iter_digests())) == 1
