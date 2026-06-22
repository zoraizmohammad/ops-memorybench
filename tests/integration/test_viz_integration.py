"""Integration tests for counterfactual exploration and time travel views."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ombench.eval.tasks import TaskSpec
from ombench.events.store import EventStore
from ombench.integrations.gcal.sync import GCalSync
from ombench.llm.stub import StubLLM
from ombench.storage import open_store
from ombench.timeutil import UTC, FrozenClock
from ombench.viz.counterfactual import MemoryPack, explore
from ombench.viz.timetravel import entity_timeline, render_timeline_text, workspace_activity

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def synced(config):
    store = open_store(config)
    es = EventStore(store.backend, store.blobs)
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    GCalSync(es, clock=clock, fixtures_path=FIXTURES / "gcal" / "calendar.json").run_sync()
    yield store, es
    store.close()


def test_time_travel_entity_timeline(synced):
    _, es = synced
    frames = entity_timeline(es, "gcal", "event", "ev_1on1_bob")
    # The 1:1 was rescheduled, so there is more than one frame and the start changes.
    assert len(frames) >= 2
    starts = [f.full.get("start") for f in frames]
    assert "2026-05-20T09:00:00-07:00" in starts
    assert "2026-05-20T15:00:00-07:00" in starts
    assert "gcal" not in render_timeline_text(frames)  # text renders steps, not app names


def test_workspace_activity_feed(synced):
    _, es = synced
    feed = workspace_activity(es)
    assert feed
    assert all("valid_at" in e and "op" in e for e in feed)


def test_counterfactual_explorer_ranks_packs(synced):
    store, _ = synced
    task = TaskSpec(
        task_id="reschedule", prompt="Reschedule my 1:1 with Bob",
        as_of_valid="2026-05-10T00:00:00Z", as_of_ingest="2026-06-01T00:00:00Z",
        memory_expected=["prefers afternoons"],
        expected_writes=[{"app": "gcal", "action": "update_event", "expect": {"start": "15:00"}}],
    )
    # Build the seeded state for the snapshot time.
    from ombench.snapshots import SnapshotMaterializer
    from ombench.timeutil import from_iso
    mat = SnapshotMaterializer(store)
    snap = mat.materialize(as_of_valid=from_iso("2026-05-10T00:00:00Z"),
                           as_of_ingest=from_iso("2026-06-01T00:00:00Z"), persist=False)
    state = {}
    for e in snap.entities:
        m = mat.events.materialize_entity(e.app, e.entity_type, e.entity_id,
                                          as_of_valid=snap.as_of_valid_time,
                                          as_of_ingest=snap.as_of_ingest_time)
        state[f"{e.app}/{e.entity_type}/{e.entity_id}"] = {
            "payload": m.payload if m else {}, "edges": {}, "deleted": e.deleted,
        }

    packs = [
        MemoryPack("with_preference", ["user prefers afternoons and avoids Fridays"]),
        MemoryPack("empty", []),
        MemoryPack("wrong", ["user prefers mornings"]),
    ]
    results = explore(task, state, packs, llm=StubLLM())
    # The afternoon pack should rank first because it satisfies the assertion.
    assert results[0].pack == "with_preference"
    assert results[0].scores.total >= results[-1].scores.total
