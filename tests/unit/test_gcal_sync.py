"""Tests for the Google Calendar sync adapter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ombench.events.store import EventStore
from ombench.integrations.gcal import normalize as norm
from ombench.integrations.gcal.sync import GCalSync
from ombench.storage import open_memory_store
from ombench.timeutil import UTC, FrozenClock, from_iso

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "gcal" / "calendar.json"


@pytest.fixture
def store():
    s = open_memory_store()
    yield EventStore(s.backend, s.blobs)
    s.close()


def test_normalize_detects_cancelled():
    assert norm.is_cancelled({"status": "cancelled"})
    assert not norm.is_cancelled({"status": "confirmed"})


def test_event_start_at_parses_datetime():
    dt = norm.event_start_at({"start": {"dateTime": "2026-05-20T09:00:00-07:00"}})
    assert dt == from_iso("2026-05-20T16:00:00Z")


def test_incremental_sync_advances_cursor(store):
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    sync = GCalSync(store, clock=clock, fixtures_path=FIXTURE)
    # First sync consumes batch 1 only? No: with no token, it consumes all batches.
    sync.run_sync()
    # The cursor now points at the last batch token.
    assert store.get_cursor("gcal", "alice@acme.com") == "TOKEN_2"


def test_reschedule_is_time_travelable(store):
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    GCalSync(store, clock=clock, fixtures_path=FIXTURE).run_sync()
    # Latest state reflects the 3pm reschedule.
    latest = store.materialize_entity("gcal", "event", "ev_1on1_bob")
    assert latest.payload["start"] == "2026-05-20T15:00:00-07:00"
    # As of before the reschedule update time, the 9am slot stands.
    before = from_iso("2026-05-10T00:00:00Z")
    earlier = store.materialize_entity("gcal", "event", "ev_1on1_bob", as_of_valid=before)
    assert earlier.payload["start"] == "2026-05-20T09:00:00-07:00"


def test_cancelled_event_is_deleted(store):
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    GCalSync(store, clock=clock, fixtures_path=FIXTURE).run_sync()
    # ev_offsite was cancelled and must not appear in live state.
    states = store.materialize(app="gcal")
    assert ("gcal", "event", "ev_offsite") not in states
    # But it is retained as a tombstone.
    with_deleted = store.materialize(app="gcal", include_deleted=True)
    assert with_deleted[("gcal", "event", "ev_offsite")].deleted


def test_attendee_edges(store):
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    GCalSync(store, clock=clock, fixtures_path=FIXTURE).run_sync()
    standup = store.materialize_entity("gcal", "event", "ev_standup")
    assert standup.edges["attendee"] == {"alice@acme.com", "carol@acme.com"}


def test_resync_idempotent(store):
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    sync = GCalSync(store, clock=clock, fixtures_path=FIXTURE)
    sync.run_sync()
    count = store.count()
    # Re running with the cursor at TOKEN_2 finds no new batches.
    second = sync.run_sync()
    assert second.events_emitted == 0
    assert store.count() == count


def test_force_resync_replays_all(store):
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    sync = GCalSync(store, clock=clock, fixtures_path=FIXTURE)
    sync.run_sync()
    sync.force_resync()
    # After a forced resync the cursor is cleared, so a sync re emits all events
    # but appends none anew because event ids are deterministic.
    second = sync.run_sync()
    assert second.events_emitted > 0
    assert second.events_new == 0
