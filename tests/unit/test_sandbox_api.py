"""Tests for the per app sandbox APIs and tool router."""

from __future__ import annotations

from datetime import datetime

import pytest

from ombench.replay.sandbox import Sandbox
from ombench.replay.sandbox_api import SandboxToolRouter
from ombench.timeutil import UTC

STATE = {
    "gcal/event/ev_1on1_bob": {
        "payload": {"id": "ev_1on1_bob", "summary": "1:1 Bob", "start": "09:00"},
        "edges": {}, "deleted": False,
    },
    "slack/channel/C_LAUNCH": {
        "payload": {"id": "C_LAUNCH", "name": "launch-redwood"}, "edges": {}, "deleted": False,
    },
    "slack/channel/C_ANNOUNCE": {
        "payload": {"id": "C_ANNOUNCE", "name": "announcements"}, "edges": {}, "deleted": False,
    },
    "gdocs/document/doc1": {
        "payload": {"id": "doc1", "name": "Overview", "markdown": "# Overview"}, "edges": {}, "deleted": False,
    },
}


@pytest.fixture
def router():
    sb = Sandbox(STATE, as_of=datetime(2026, 5, 14, 17, 0, 0, tzinfo=UTC))
    return SandboxToolRouter(sb)


def test_tools_listed(router):
    names = {t.name for t in router.tools()}
    assert "slack.post_message" in names
    assert "gcal.update_event" in names
    assert "gdocs.create_document" in names


def test_slack_list_channels(router):
    result, refs = router.execute("slack.list_channels", {})
    assert "announcements" in result["channels"]
    assert any(r.entity_type == "channel" for r in refs)


def test_slack_post_resolves_channel_name_to_id(router):
    result, refs = router.execute("slack.post_message", {"channel": "announcements", "text": "Launch is live"})
    assert result["ok"]
    # The channel name resolves to its id in the ref, while the write records both
    # the named intent and the resolved id.
    assert refs[0].entity_id == "C_ANNOUNCE"
    writes = router.sandbox.writes_for("slack")
    assert writes[0].payload["channel"] == "announcements"
    assert writes[0].payload["channel_id"] == "C_ANNOUNCE"


def test_gcal_get_event(router):
    result, refs = router.execute("gcal.get_event", {"event_id": "ev_1on1_bob"})
    assert result["start"] == "09:00"
    assert refs[0].role == "read"


def test_gcal_update_event_records_write(router):
    result, refs = router.execute("gcal.update_event", {"event_id": "ev_1on1_bob", "start": "15:00"})
    assert result["ok"]
    assert refs[0].role == "write"
    # Read state is unchanged; the write is in the log.
    assert router.sandbox.get_entity("gcal", "event", "ev_1on1_bob")["payload"]["start"] == "09:00"
    assert router.sandbox.writes_for("gcal")[0].payload["start"] == "15:00"


def test_gdocs_create_and_read(router):
    result, refs = router.execute("gdocs.create_document", {"name": "Customer Acme 2026-05-20"})
    assert result["ok"]
    read, _ = router.execute("gdocs.get_document", {"document_id": "doc1"})
    assert read["name"] == "Overview"


def test_unknown_tool(router):
    result, refs = router.execute("nope.frobnicate", {})
    assert "error" in result
    assert refs == []
