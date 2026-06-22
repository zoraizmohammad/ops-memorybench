"""Tests for the Slack sync adapter and normalizer."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ombench.events.queries import list_entities
from ombench.events.store import EventStore
from ombench.integrations.slack import normalize as norm
from ombench.integrations.slack.sync import SlackSync
from ombench.storage import open_memory_store
from ombench.timeutil import UTC, FrozenClock

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "slack" / "workspace.json"


@pytest.fixture
def store():
    s = open_memory_store()
    yield EventStore(s.backend, s.blobs)
    s.close()


@pytest.fixture
def synced(store):
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    sync = SlackSync(store, clock=clock, fixtures_path=FIXTURE)
    sync.run_sync()
    return store


def test_normalize_message_id():
    assert norm.message_id("C1", "123.456") == "C1:123.456"


def test_normalize_channel_topic_string_and_object():
    assert norm.normalize_channel({"id": "C1", "topic": "hi"})["topic"] == "hi"
    obj = norm.normalize_channel({"id": "C1", "topic": {"value": "deep"}})
    assert obj["topic"] == "deep"


def test_sync_emits_users_channels_messages(synced):
    users = list_entities(synced, app="slack", entity_type="user")
    channels = list_entities(synced, app="slack", entity_type="channel")
    messages = list_entities(synced, app="slack", entity_type="message")
    assert len(users) == 3
    assert len(channels) == 3
    assert len(messages) == 5  # 3 + 1 + 1


def test_channel_membership_edges(synced):
    launch = synced.materialize_entity("slack", "channel", "C_LAUNCH")
    assert launch.edges["member"] == {"U_ALICE", "U_BOB"}
    general = synced.materialize_entity("slack", "channel", "C_GENERAL")
    assert general.edges["member"] == {"U_ALICE", "U_BOB", "U_CAROL"}


def test_message_edit_is_versioned(synced):
    # The edited message should reflect the latest text after the edit version.
    msg = synced.materialize_entity("slack", "message", "C_LAUNCH:1715000600.000200")
    assert "announcements channel" in msg.payload["text"]
    assert msg.version_count == 1


def test_message_time_travel_before_edit(synced):
    # Before the edit time, the original text stands.
    from ombench.timeutil import from_epoch

    before = from_epoch("1715000700.000000")  # after post, before edit
    msg = synced.materialize_entity(
        "slack", "message", "C_LAUNCH:1715000600.000200", as_of_valid=before
    )
    assert msg.payload["text"].startswith("We announce launches in announcements")
    assert "the announcements channel using" not in msg.payload["text"]


def test_resync_is_idempotent(store):
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    sync = SlackSync(store, clock=clock, fixtures_path=FIXTURE)
    sync.run_sync()
    count_after_first = store.count()
    second = sync.run_sync()
    assert second.events_new == 0
    assert store.count() == count_after_first


def test_cursor_persisted(synced):
    assert synced.get_cursor("slack", "workspace") == "T_ACME"


def test_not_live_with_fixtures(store):
    sync = SlackSync(store, fixtures_path=FIXTURE)
    assert sync.is_live is False


def test_reactions_emitted(synced):
    # The announcement message carries a tada reaction recorded as a status change.
    rows = list(synced.iter_events(app="slack", entity_id="C_ANNOUNCE:1714000000.000100", load_payload=True))
    ops = {r["op"] for r in rows}
    assert "status_change" in ops
