"""Tests for the canonical event schema and algebra."""

from __future__ import annotations

from datetime import datetime

import pytest

from ombench.events import algebra
from ombench.events.schema import App, AppEvent, Op
from ombench.timeutil import UTC

VALID = datetime(2026, 5, 14, 17, 0, 0, tzinfo=UTC)
INGEST = datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC)


def test_event_id_is_deterministic():
    e1 = algebra.upsert_entity(
        app="slack", entity_type="message", entity_id="m1",
        payload={"text": "hi"}, valid_at=VALID, ingested_at=INGEST,
    )
    e2 = algebra.upsert_entity(
        app="slack", entity_type="message", entity_id="m1",
        payload={"text": "hi"}, valid_at=VALID, ingested_at=INGEST,
    )
    assert e1.event_id == e2.event_id


def test_event_id_changes_with_payload():
    e1 = algebra.upsert_entity(
        app="slack", entity_type="message", entity_id="m1",
        payload={"text": "hi"}, valid_at=VALID, ingested_at=INGEST,
    )
    e2 = algebra.upsert_entity(
        app="slack", entity_type="message", entity_id="m1",
        payload={"text": "bye"}, valid_at=VALID, ingested_at=INGEST,
    )
    assert e1.event_id != e2.event_id


def test_payload_hash_matches_content():
    from ombench.ids import content_hash

    e = algebra.upsert_entity(
        app="gcal", entity_type="event", entity_id="ev1",
        payload={"summary": "1:1"}, valid_at=VALID, ingested_at=INGEST,
    )
    assert e.payload_hash == content_hash({"summary": "1:1"})


def test_times_coerced_to_utc():
    naive = datetime(2026, 5, 14, 17, 0, 0)
    e = algebra.upsert_entity(
        app="slack", entity_type="message", entity_id="m1",
        payload={}, valid_at=naive, ingested_at=naive,
    )
    assert e.valid_at.tzinfo == UTC


def test_event_is_frozen():
    from pydantic import ValidationError

    e = algebra.upsert_entity(
        app="slack", entity_type="message", entity_id="m1",
        payload={}, valid_at=VALID, ingested_at=INGEST,
    )
    with pytest.raises(ValidationError):
        e.entity_id = "other"  # type: ignore[misc]


def test_delete_entity_flags():
    e = algebra.delete_entity(
        app="gcal", entity_type="event", entity_id="ev1",
        valid_at=VALID, ingested_at=INGEST,
    )
    assert e.is_delete
    assert e.op == Op.DELETE_ENTITY


def test_edge_helpers():
    e = algebra.upsert_edge(
        app="slack", entity_type="channel", entity_id="C1",
        edge_kind="member", edge_target="U1", valid_at=VALID, ingested_at=INGEST,
    )
    assert e.is_edge
    assert e.edge_kind == "member"
    assert e.edge_target == "U1"

    d = algebra.delete_edge(
        app="slack", entity_type="channel", entity_id="C1",
        edge_kind="member", edge_target="U1", valid_at=VALID, ingested_at=INGEST,
    )
    assert d.op == Op.DELETE_EDGE


def test_append_version_and_status_change():
    v = algebra.append_version(
        app="gdocs", entity_type="document", entity_id="d1",
        payload={"markdown": "# Title"}, valid_at=VALID, ingested_at=INGEST,
    )
    assert v.op == Op.APPEND_VERSION

    s = algebra.status_change(
        app="gcal", entity_type="attendee", entity_id="a1",
        payload={"response": "accepted"}, valid_at=VALID, ingested_at=INGEST,
    )
    assert s.op == Op.STATUS_CHANGE


def test_entity_key():
    e = algebra.upsert_entity(
        app="slack", entity_type="message", entity_id="m1",
        payload={}, valid_at=VALID, ingested_at=INGEST,
    )
    assert e.entity_key() == ("slack", "message", "m1")


def test_app_enum_accepts_string():
    e = AppEvent(
        app="slack", entity_type="message", entity_id="m1", op=Op.UPSERT_ENTITY,
        payload={}, valid_at=VALID, ingested_at=INGEST,
    )
    assert e.app == App.SLACK
