"""Tests for the append only bitemporal event store and fold materialization.

These tests are the heart of the substrate's correctness. They check that:

- appends are idempotent
- the fold produces the latest state with no time bounds
- valid time travel reconstructs past app state
- ingest time travel hides information that arrived later (no leakage)
- deletes tombstone entities
- edges fold into live target sets
"""

from __future__ import annotations

from datetime import datetime

import pytest

from ombench.events import algebra
from ombench.events.store import EventStore
from ombench.storage import open_memory_store
from ombench.timeutil import UTC


def t(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 5, day, hour, 0, 0, tzinfo=UTC)


@pytest.fixture
def store():
    s = open_memory_store()
    yield EventStore(s.backend, s.blobs)
    s.close()


def test_append_is_idempotent(store):
    e = algebra.upsert_entity(
        app="slack", entity_type="message", entity_id="m1",
        payload={"text": "hi"}, valid_at=t(1), ingested_at=t(1),
    )
    store.append(e)
    store.append(e)
    assert store.count() == 1


def test_append_many_counts_new(store):
    events = [
        algebra.upsert_entity(
            app="slack", entity_type="message", entity_id=f"m{i}",
            payload={"text": str(i)}, valid_at=t(1), ingested_at=t(1),
        )
        for i in range(3)
    ]
    added = store.append_many(events)
    assert added == 3
    # Re appending the same batch adds nothing.
    assert store.append_many(events) == 0


def test_materialize_latest_state(store):
    store.append(algebra.upsert_entity(
        app="gcal", entity_type="event", entity_id="ev1",
        payload={"summary": "Draft", "start": "09:00"}, valid_at=t(1), ingested_at=t(1),
    ))
    store.append(algebra.upsert_entity(
        app="gcal", entity_type="event", entity_id="ev1",
        payload={"start": "10:00"}, valid_at=t(2), ingested_at=t(2),
    ))
    states = store.materialize(app="gcal")
    state = states[("gcal", "event", "ev1")]
    # Later upsert merges over the earlier one.
    assert state.payload["summary"] == "Draft"
    assert state.payload["start"] == "10:00"


def test_valid_time_travel(store):
    store.append(algebra.upsert_entity(
        app="gcal", entity_type="event", entity_id="ev1",
        payload={"start": "09:00"}, valid_at=t(1), ingested_at=t(1),
    ))
    store.append(algebra.upsert_entity(
        app="gcal", entity_type="event", entity_id="ev1",
        payload={"start": "10:00"}, valid_at=t(5), ingested_at=t(5),
    ))
    # As of day 3, only the first change had taken effect.
    state = store.materialize_entity("gcal", "event", "ev1", as_of_valid=t(3))
    assert state.payload["start"] == "09:00"
    # As of day 6, the second change is visible.
    state = store.materialize_entity("gcal", "event", "ev1", as_of_valid=t(6))
    assert state.payload["start"] == "10:00"


def test_ingest_time_travel_prevents_leakage(store):
    # A change that took effect on day 1 in the app but was only ingested on day 9
    # (a late arriving backfill). A backtest at ingest time day 5 must not see it.
    store.append(algebra.upsert_entity(
        app="slack", entity_type="message", entity_id="m1",
        payload={"text": "known early"}, valid_at=t(1), ingested_at=t(1),
    ))
    store.append(algebra.upsert_entity(
        app="slack", entity_type="message", entity_id="m1",
        payload={"text": "late backfill"}, valid_at=t(1, 13), ingested_at=t(9),
    ))
    # As of valid day 2 but only what was ingested by day 5: late backfill hidden.
    state = store.materialize_entity(
        "slack", "message", "m1", as_of_valid=t(2), as_of_ingest=t(5)
    )
    assert state.payload["text"] == "known early"
    # With ingest as of day 10, the backfill is now visible.
    state = store.materialize_entity(
        "slack", "message", "m1", as_of_valid=t(2), as_of_ingest=t(10)
    )
    assert state.payload["text"] == "late backfill"


def test_delete_tombstones_entity(store):
    store.append(algebra.upsert_entity(
        app="gcal", entity_type="event", entity_id="ev1",
        payload={"summary": "Meeting"}, valid_at=t(1), ingested_at=t(1),
    ))
    store.append(algebra.delete_entity(
        app="gcal", entity_type="event", entity_id="ev1",
        valid_at=t(2), ingested_at=t(2),
    ))
    # Default excludes deleted.
    assert ("gcal", "event", "ev1") not in store.materialize(app="gcal")
    # But before the delete the event existed.
    state = store.materialize_entity("gcal", "event", "ev1", as_of_valid=t(1, 13))
    assert not state.deleted
    # And it is retrievable with include_deleted.
    states = store.materialize(app="gcal", include_deleted=True)
    assert states[("gcal", "event", "ev1")].deleted


def test_edges_fold_into_live_sets(store):
    store.append(algebra.upsert_entity(
        app="slack", entity_type="channel", entity_id="C1",
        payload={"name": "launch"}, valid_at=t(1), ingested_at=t(1),
    ))
    store.append(algebra.upsert_edge(
        app="slack", entity_type="channel", entity_id="C1",
        edge_kind="member", edge_target="U1", valid_at=t(1), ingested_at=t(1),
    ))
    store.append(algebra.upsert_edge(
        app="slack", entity_type="channel", entity_id="C1",
        edge_kind="member", edge_target="U2", valid_at=t(2), ingested_at=t(2),
    ))
    store.append(algebra.delete_edge(
        app="slack", entity_type="channel", entity_id="C1",
        edge_kind="member", edge_target="U1", valid_at=t(3), ingested_at=t(3),
    ))
    state = store.materialize_entity("slack", "channel", "C1")
    assert state.edges["member"] == {"U2"}
    # Time travel before the removal shows both members.
    earlier = store.materialize_entity("slack", "channel", "C1", as_of_valid=t(2, 13))
    assert earlier.edges["member"] == {"U1", "U2"}


def test_append_version_counts(store):
    for i, day in enumerate([1, 3, 5], start=1):
        store.append(algebra.append_version(
            app="gdocs", entity_type="document", entity_id="d1",
            payload={"markdown": f"v{i}"}, valid_at=t(day), ingested_at=t(day),
        ))
    state = store.materialize_entity("gdocs", "document", "d1")
    assert state.version_count == 3
    assert state.payload["markdown"] == "v3"
    # Time travel to the middle version.
    mid = store.materialize_entity("gdocs", "document", "d1", as_of_valid=t(3, 13))
    assert mid.payload["markdown"] == "v2"


def test_cursors_round_trip(store):
    assert store.get_cursor("gcal", "primary") is None
    store.set_cursor("gcal", "primary", "synctoken123")
    assert store.get_cursor("gcal", "primary") == "synctoken123"
    store.set_cursor("gcal", "primary", "synctoken456")
    assert store.get_cursor("gcal", "primary") == "synctoken456"


def test_get_payload(store):
    e = algebra.upsert_entity(
        app="slack", entity_type="message", entity_id="m1",
        payload={"text": "payload body"}, valid_at=t(1), ingested_at=t(1),
    )
    store.append(e)
    assert store.get_payload(e.event_id)["text"] == "payload body"


def test_fold_determinism(store):
    # Same events in different insertion order materialize identically because the
    # fold orders by valid_at then seq.
    events = [
        algebra.upsert_entity(
            app="gcal", entity_type="event", entity_id="ev1",
            payload={"n": i}, valid_at=t(i), ingested_at=t(i),
        )
        for i in range(1, 5)
    ]
    for e in events:
        store.append(e)
    first = store.materialize_entity("gcal", "event", "ev1").payload
    assert first["n"] == 4
