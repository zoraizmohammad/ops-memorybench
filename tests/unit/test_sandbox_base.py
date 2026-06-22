"""Tests for the sandbox base."""

from __future__ import annotations

from datetime import datetime

from ombench.replay.sandbox import Sandbox
from ombench.timeutil import UTC

STATE = {
    "gcal/event/ev1": {"payload": {"summary": "1:1", "start": "09:00"}, "edges": {}, "deleted": False},
    "gcal/event/ev2": {"payload": {"summary": "standup"}, "edges": {}, "deleted": True},
    "slack/channel/C1": {"payload": {"name": "launch"}, "edges": {"member": ["U1"]}, "deleted": False},
}


def _sandbox():
    return Sandbox(STATE, as_of=datetime(2026, 5, 14, 17, 0, 0, tzinfo=UTC))


def test_frozen_clock():
    sb = _sandbox()
    assert sb.now == datetime(2026, 5, 14, 17, 0, 0, tzinfo=UTC)
    assert sb.now == sb.now  # constant


def test_entities_excludes_deleted():
    sb = _sandbox()
    events = sb.entities("gcal", "event")
    summaries = {e["payload"]["summary"] for e in events}
    assert summaries == {"1:1"}  # ev2 is deleted


def test_get_entity():
    sb = _sandbox()
    assert sb.get_entity("gcal", "event", "ev1")["payload"]["start"] == "09:00"
    assert sb.get_entity("gcal", "event", "ev2") is None  # deleted
    assert sb.get_entity("gcal", "event", "absent") is None


def test_find_entity():
    sb = _sandbox()
    found = sb.find_entity("slack", "channel", name="launch")
    assert found is not None
    assert sb.find_entity("slack", "channel", name="absent") is None


def test_writes_recorded_not_mutating_state():
    sb = _sandbox()
    sb.apply_write("gcal", "update_event", {"event_id": "ev1", "start": "15:00"})
    # The read state is unchanged.
    assert sb.get_entity("gcal", "event", "ev1")["payload"]["start"] == "09:00"
    # The write is recorded with the frozen timestamp.
    assert len(sb.writes) == 1
    assert sb.writes[0].at == sb.now


def test_writes_for_app():
    sb = _sandbox()
    sb.apply_write("gcal", "update_event", {})
    sb.apply_write("slack", "post_message", {})
    assert len(sb.writes_for("gcal")) == 1
    assert len(sb.writes_for("slack")) == 1


def test_reset_clears_writes():
    sb = _sandbox()
    sb.apply_write("gcal", "update_event", {})
    sb.reset()
    assert sb.writes == []
