"""Tests for the integration base interfaces."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import pytest

from ombench.events import algebra
from ombench.events.schema import App, AppEvent
from ombench.events.store import EventStore
from ombench.integrations.base import Integration, IntegrationSandbox, SyncResult
from ombench.storage import open_memory_store
from ombench.timeutil import UTC, FrozenClock


class DummyIntegration(Integration):
    app = App.SLACK
    entity_types = ("message",)

    def __init__(self, store, messages, **kw):
        super().__init__(store, **kw)
        self._messages = messages

    def sync(self, *, ingested_at) -> Iterator[AppEvent]:
        for i, text in enumerate(self._messages):
            yield algebra.upsert_entity(
                app="slack", entity_type="message", entity_id=f"m{i}",
                payload={"text": text},
                valid_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
                ingested_at=ingested_at,
            )


@pytest.fixture
def store():
    s = open_memory_store()
    yield EventStore(s.backend, s.blobs)
    s.close()


def test_run_sync_appends_events(store):
    clock = FrozenClock(datetime(2026, 5, 2, tzinfo=UTC))
    integ = DummyIntegration(store, ["hello", "world"], clock=clock)
    result = integ.run_sync()
    assert result.events_emitted == 2
    assert result.events_new == 2
    assert store.count() == 2


def test_run_sync_is_idempotent(store):
    clock = FrozenClock(datetime(2026, 5, 2, tzinfo=UTC))
    integ = DummyIntegration(store, ["a", "b"], clock=clock)
    integ.run_sync()
    second = integ.run_sync()
    # Re sync emits the same events but appends none anew.
    assert second.events_emitted == 2
    assert second.events_new == 0
    assert store.count() == 2


def test_default_not_live(store):
    integ = DummyIntegration(store, [])
    assert integ.is_live is False


def test_sync_result_repr():
    r = SyncResult()
    r.events_emitted = 3
    assert "emitted=3" in repr(r)


class DummySandbox(IntegrationSandbox):
    app = App.SLACK


def test_sandbox_records_writes():
    sb = DummySandbox({"channels": {}}, now=datetime(2026, 5, 14, tzinfo=UTC))
    resp = sb.record_write("post_message", {"channel": "C1", "text": "hi"})
    assert resp["ok"] is True
    assert len(sb.writes) == 1
    assert sb.writes[0]["action"] == "post_message"
