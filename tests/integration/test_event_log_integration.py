"""Integration tests exercising the full Phase 1 stack together.

These run the relational backend, blob store, event store, and query helpers as a
unit against an on disk store to confirm the layers compose correctly and survive a
close and reopen, which the long lived worker depends on.
"""

from __future__ import annotations

from datetime import datetime

from ombench.events import algebra
from ombench.events.queries import entity_history, list_entities, stats, timeline
from ombench.events.store import EventStore
from ombench.storage import open_store
from ombench.timeutil import UTC


def t(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 5, day, hour, 0, 0, tzinfo=UTC)


def seed(store: EventStore) -> None:
    store.append_many([
        algebra.upsert_entity(
            app="slack", entity_type="channel", entity_id="C1",
            payload={"name": "launch-redwood"}, valid_at=t(1), ingested_at=t(1),
        ),
        algebra.upsert_entity(
            app="slack", entity_type="message", entity_id="m1",
            payload={"text": "kickoff", "channel": "C1"}, valid_at=t(2), ingested_at=t(2),
        ),
        algebra.upsert_entity(
            app="gcal", entity_type="event", entity_id="ev1",
            payload={"summary": "1:1", "start": "09:00"}, valid_at=t(2), ingested_at=t(2),
        ),
        algebra.upsert_entity(
            app="gcal", entity_type="event", entity_id="ev1",
            payload={"start": "14:00"}, valid_at=t(4), ingested_at=t(4),
        ),
    ])


def test_full_stack_persists_and_reopens(config):
    store_handle = open_store(config)
    es = EventStore(store_handle.backend, store_handle.blobs)
    seed(es)
    assert es.count() == 4
    store_handle.close()

    # Reopen the same on disk store and confirm history survived.
    reopened = open_store(config)
    es2 = EventStore(reopened.backend, reopened.blobs)
    assert es2.count() == 4
    state = es2.materialize_entity("gcal", "event", "ev1")
    assert state.payload["start"] == "14:00"
    reopened.close()


def test_entity_history(config):
    store_handle = open_store(config)
    es = EventStore(store_handle.backend, store_handle.blobs)
    seed(es)
    hist = entity_history(es, "gcal", "event", "ev1")
    assert len(hist) == 2
    assert hist[0].payload["start"] == "09:00"
    assert hist[1].payload["start"] == "14:00"
    store_handle.close()


def test_list_entities_filters_and_sorts(config):
    store_handle = open_store(config)
    es = EventStore(store_handle.backend, store_handle.blobs)
    seed(es)
    slack_entities = list_entities(es, app="slack")
    keys = [(s.entity_type, s.entity_id) for s in slack_entities]
    assert keys == [("channel", "C1"), ("message", "m1")]

    only_events = list_entities(es, app="gcal", entity_type="event")
    assert len(only_events) == 1
    store_handle.close()


def test_timeline_window(config):
    store_handle = open_store(config)
    es = EventStore(store_handle.backend, store_handle.blobs)
    seed(es)
    window = timeline(es, start=t(2), end=t(3))
    # Only the day 2 events fall in the window.
    valid_days = {row["valid_at"][:10] for row in window}
    assert valid_days == {"2026-05-02"}
    store_handle.close()


def test_stats(config):
    store_handle = open_store(config)
    es = EventStore(store_handle.backend, store_handle.blobs)
    seed(es)
    s = stats(es)
    assert s["total"] == 4
    assert s["by_app"]["slack"] == 2
    assert s["by_app"]["gcal"] == 2
    assert s["by_op"]["upsert_entity"] == 4
    store_handle.close()


def test_list_entities_as_of_valid(config):
    store_handle = open_store(config)
    es = EventStore(store_handle.backend, store_handle.blobs)
    seed(es)
    # As of day 1 only the channel exists.
    early = list_entities(es, as_of_valid=t(1, 13))
    keys = [(s.app, s.entity_type, s.entity_id) for s in early]
    assert keys == [("slack", "channel", "C1")]
    store_handle.close()
