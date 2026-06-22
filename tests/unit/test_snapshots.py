"""Tests for snapshot materialization and diffing."""

from __future__ import annotations

from datetime import datetime

import pytest

from ombench.events import algebra
from ombench.events.store import EventStore
from ombench.snapshots import (
    SnapshotMaterializer,
    compute_root_hash,
    diff_snapshots,
)
from ombench.storage import open_memory_store
from ombench.timeutil import UTC


def t(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 5, day, hour, 0, 0, tzinfo=UTC)


@pytest.fixture
def store():
    return open_memory_store()


@pytest.fixture
def seeded(store):
    es = EventStore(store.backend, store.blobs)
    es.append(algebra.upsert_entity(
        app="gcal", entity_type="event", entity_id="ev1",
        payload={"summary": "1:1", "start": "09:00"}, valid_at=t(1), ingested_at=t(1),
    ))
    es.append(algebra.upsert_entity(
        app="gcal", entity_type="event", entity_id="ev2",
        payload={"summary": "standup"}, valid_at=t(1), ingested_at=t(1),
    ))
    es.append(algebra.upsert_entity(
        app="gcal", entity_type="event", entity_id="ev1",
        payload={"start": "14:00"}, valid_at=t(5), ingested_at=t(5),
    ))
    es.append(algebra.delete_entity(
        app="gcal", entity_type="event", entity_id="ev2",
        valid_at=t(6), ingested_at=t(6),
    ))
    return store


def test_root_hash_order_independent():
    a = compute_root_hash(["h1", "h2", "h3"])
    b = compute_root_hash(["h3", "h1", "h2"])
    assert a == b


def test_empty_snapshot_has_stable_root():
    assert compute_root_hash([]) == compute_root_hash([])


def test_materialize_latest(seeded):
    mat = SnapshotMaterializer(seeded)
    snap = mat.materialize(app="gcal", as_of_valid=t(10), as_of_ingest=t(10))
    # ev2 deleted, so one live entity remains plus the tombstone is tracked.
    live = [e for e in snap.entities if not e.deleted]
    assert len(live) == 1
    assert live[0].entity_id == "ev1"


def test_snapshot_persisted_and_reloadable(seeded):
    mat = SnapshotMaterializer(seeded)
    snap = mat.materialize(app="gcal", as_of_valid=t(10), as_of_ingest=t(10), label="latest")
    reloaded = mat.get_manifest(snap.snapshot_id)
    assert reloaded is not None
    assert reloaded.root_hash == snap.root_hash
    state = mat.load_state(snap.snapshot_id)
    assert "gcal/event/ev1" in state
    assert state["gcal/event/ev1"]["payload"]["start"] == "14:00"


def test_historical_snapshot_differs_from_latest(seeded):
    mat = SnapshotMaterializer(seeded)
    early = mat.materialize(app="gcal", as_of_valid=t(2), as_of_ingest=t(2), persist=False)
    late = mat.materialize(app="gcal", as_of_valid=t(10), as_of_ingest=t(10), persist=False)
    assert early.root_hash != late.root_hash


def test_identical_state_same_root(seeded):
    mat = SnapshotMaterializer(seeded)
    a = mat.materialize(app="gcal", as_of_valid=t(10), as_of_ingest=t(10), persist=False)
    b = mat.materialize(app="gcal", as_of_valid=t(11), as_of_ingest=t(11), persist=False)
    # No events between t(10) and t(11), so identical state and identical root.
    assert a.root_hash == b.root_hash


def test_diff_reschedule_and_delete(seeded):
    mat = SnapshotMaterializer(seeded)
    before = mat.materialize(app="gcal", as_of_valid=t(2), as_of_ingest=t(2), persist=False)
    after = mat.materialize(app="gcal", as_of_valid=t(10), as_of_ingest=t(10), persist=False)
    diff = diff_snapshots(before, after)
    # ev1 changed (rescheduled), ev2 removed (deleted).
    assert "gcal/event/ev1" in diff.changed
    assert "gcal/event/ev2" in diff.removed
    assert not diff.is_empty


def test_diff_empty_for_same_snapshot(seeded):
    mat = SnapshotMaterializer(seeded)
    snap = mat.materialize(app="gcal", as_of_valid=t(10), as_of_ingest=t(10), persist=False)
    diff = diff_snapshots(snap, snap)
    assert diff.is_empty


def test_list_snapshots(seeded):
    mat = SnapshotMaterializer(seeded)
    mat.materialize(app="gcal", as_of_valid=t(2), as_of_ingest=t(2), label="early")
    mat.materialize(app="gcal", as_of_valid=t(10), as_of_ingest=t(10), label="late")
    snaps = mat.list_snapshots()
    assert len(snaps) == 2
    labels = {s["label"] for s in snaps}
    assert labels == {"early", "late"}
