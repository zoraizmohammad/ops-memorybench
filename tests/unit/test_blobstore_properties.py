"""Property based tests for content addressing invariants.

The blob store and canonical JSON encoder underpin every other layer, so their
core invariants are worth checking against generated inputs rather than only hand
written examples.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from ombench.ids import canonical_json, content_hash
from ombench.storage.blobstore import BlobStore

# JSON-like values: nested dicts, lists, strings, ints, bools, None.
json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**9), max_value=10**9),
    st.text(max_size=50),
)
json_values = st.recursive(
    json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=20), children, max_size=5),
    ),
    max_leaves=20,
)


@given(payload=json_values)
def test_content_hash_is_deterministic(payload):
    assert content_hash(payload) == content_hash(payload)


@given(payload=st.dictionaries(st.text(max_size=10), json_scalars, max_size=6))
def test_dict_key_order_does_not_change_hash(payload):
    reordered = dict(reversed(list(payload.items())))
    assert content_hash(payload) == content_hash(reordered)


@given(payload=json_values)
def test_round_trip_through_store(tmp_path_factory, payload):
    store = BlobStore(tmp_path_factory.mktemp("blobs"))
    digest = store.put_json(payload)
    assert store.get_json(digest) == payload


@given(payload=json_values)
def test_hash_matches_canonical_json(payload):
    assert content_hash(payload) == content_hash(payload)
    # The hash is exactly the sha of the canonical encoding.
    from ombench.ids import sha256_hex

    assert content_hash(payload) == sha256_hex(canonical_json(payload))
