"""End to end test of the full Task 2 loop.

Runs all three integrations from fixtures into one event log, then materializes
snapshots at different points in time and confirms they reconstruct the right
historical state and diff correctly. This is the integration that proves "git for
SaaS" works across apps.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ombench.events.store import EventStore
from ombench.integrations.gcal.sync import GCalSync
from ombench.integrations.gdocs.sync import GDocsSync
from ombench.integrations.slack.sync import SlackSync
from ombench.snapshots import SnapshotMaterializer, diff_snapshots
from ombench.storage import open_store
from ombench.timeutil import UTC, FrozenClock, from_iso

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def _sync_all(store):
    es = EventStore(store.backend, store.blobs)
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    SlackSync(es, clock=clock, fixtures_path=FIXTURES / "slack" / "workspace.json").run_sync()
    GCalSync(es, clock=clock, fixtures_path=FIXTURES / "gcal" / "calendar.json").run_sync()
    GDocsSync(es, clock=clock, fixtures_path=FIXTURES / "gdocs" / "docs.json").run_sync()
    return es


@pytest.fixture
def synced(config):
    store = open_store(config)
    _sync_all(store)
    yield store
    store.close()


def test_all_apps_ingested(synced):
    es = EventStore(synced.backend, synced.blobs)
    states = es.materialize()
    apps = {key[0] for key in states}
    assert apps == {"slack", "gcal", "gdocs"}


def test_cross_app_snapshot(synced):
    mat = SnapshotMaterializer(synced)
    snap = mat.materialize(as_of_valid=from_iso("2026-06-01T00:00:00Z"),
                           as_of_ingest=from_iso("2026-06-01T00:00:00Z"))
    apps = {e.app for e in snap.entities if not e.deleted}
    assert apps == {"slack", "gcal", "gdocs"}
    assert snap.entity_count > 5


def test_historical_vs_latest_diff(synced):
    mat = SnapshotMaterializer(synced)
    # Before the 1:1 reschedule (which happened 2026-05-14T17:00) and before the
    # Redwood doc r2 (2026-05-12).
    before = mat.materialize(
        as_of_valid=from_iso("2026-05-02T00:00:00Z"),
        as_of_ingest=from_iso("2026-06-01T00:00:00Z"), persist=False,
    )
    after = mat.materialize(
        as_of_valid=from_iso("2026-06-01T00:00:00Z"),
        as_of_ingest=from_iso("2026-06-01T00:00:00Z"), persist=False,
    )
    diff = diff_snapshots(before, after)
    # The 1:1 event changed and the Redwood doc changed.
    assert "gcal/event/ev_1on1_bob" in diff.changed
    assert "gdocs/document/doc_redwood_overview" in diff.changed
    assert not diff.is_empty


def test_snapshot_roundtrip_persistence(synced):
    mat = SnapshotMaterializer(synced)
    snap = mat.materialize(label="full")
    state = mat.load_state(snap.snapshot_id)
    # The Redwood doc latest content is present in the snapshot state blob.
    doc = state["gdocs/document/doc_redwood_overview"]
    assert "Status ready" in doc["payload"]["markdown"]
