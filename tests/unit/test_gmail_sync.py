"""Tests for the Gmail future path adapter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ombench.events.store import EventStore
from ombench.integrations.gmail.sync import GmailSync
from ombench.storage import open_memory_store
from ombench.timeutil import UTC, FrozenClock

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "gmail" / "mailbox.json"


@pytest.fixture
def store():
    s = open_memory_store()
    yield EventStore(s.backend, s.blobs)
    s.close()


def test_gmail_messages_ingested(store):
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    GmailSync(store, clock=clock, fixtures_path=FIXTURE).run_sync()
    msg = store.materialize_entity("gmail", "message", "msg_vip_1")
    assert msg is not None
    assert msg.payload["from"] == "vip@bigcustomer.com"
    assert "IMPORTANT" in msg.payload["labelIds"]


def test_gmail_history_id_cursor(store):
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    GmailSync(store, clock=clock, fixtures_path=FIXTURE).run_sync()
    assert store.get_cursor("gmail", "mailbox") == "987654"


def test_gmail_not_live_with_fixtures(store):
    assert GmailSync(store, fixtures_path=FIXTURE).is_live is False
