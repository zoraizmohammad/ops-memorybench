"""Tests for identifier and canonicalization utilities."""

from __future__ import annotations

from datetime import datetime

from ombench.ids import (
    canonical_json,
    content_hash,
    is_content_hash,
    new_id,
    sha256_hex,
    short_hash,
)
from ombench.timeutil import UTC


def test_canonical_json_is_key_order_independent():
    a = {"b": 1, "a": 2, "c": [3, 2, 1]}
    b = {"c": [3, 2, 1], "a": 2, "b": 1}
    assert canonical_json(a) == canonical_json(b)


def test_canonical_json_is_compact_and_sorted():
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_canonical_json_serializes_datetime():
    dt = datetime(2026, 5, 14, 17, 0, 0, tzinfo=UTC)
    assert canonical_json({"t": dt}) == '{"t":"2026-05-14T17:00:00.000Z"}'


def test_canonical_json_serializes_sets_sorted():
    assert canonical_json({"s": {3, 1, 2}}) == '{"s":[1,2,3]}'


def test_content_hash_is_stable_and_dedupes():
    payload = {"hello": "world", "n": 42}
    assert content_hash(payload) == content_hash({"n": 42, "hello": "world"})


def test_content_hash_changes_with_content():
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_sha256_hex_matches_known_value():
    # SHA-256 of the empty string is a well known constant.
    assert sha256_hex("") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_short_hash_length():
    assert len(short_hash({"a": 1}, 12)) == 12
    assert len(short_hash({"a": 1}, 8)) == 8


def test_new_id_with_seed_is_deterministic():
    a = new_id("evt", seed={"x": 1})
    b = new_id("evt", seed={"x": 1})
    assert a == b
    assert a.startswith("evt_")


def test_new_id_without_seed_is_random_and_prefixed():
    a = new_id("trace")
    b = new_id("trace")
    assert a != b
    assert a.startswith("trace_")


def test_is_content_hash():
    assert is_content_hash(sha256_hex("x"))
    assert not is_content_hash("not a hash")
    assert not is_content_hash("ABC123")
    assert not is_content_hash(sha256_hex("x").upper())
