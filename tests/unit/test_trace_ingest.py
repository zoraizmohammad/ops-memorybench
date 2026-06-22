"""Tests for the trajectory ingestion pipeline."""

from __future__ import annotations

from datetime import datetime

import pytest

from ombench.storage import open_memory_store
from ombench.timeutil import UTC
from ombench.traces.ingest import TrajectoryIngestor
from ombench.traces.schema import AppRef, SpanKind, TraceRun, TraceSpan


def t(minute: int) -> datetime:
    return datetime(2026, 5, 14, 17, minute, 0, tzinfo=UTC)


@pytest.fixture
def ingestor():
    store = open_memory_store()
    yield TrajectoryIngestor(store)
    store.close()


def make_run() -> TraceRun:
    run = TraceRun(agent="claude_code", group_id="g1", started_at=t(0), task_ref="task1")
    run.add_span(TraceSpan(kind=SpanKind.AGENT, name="root", started_at=t(0)))
    run.add_span(TraceSpan(
        kind=SpanKind.TOOL, name="slack.post", tool_name="slack.post", started_at=t(1),
        input={"channel": "C1", "text": "ping alice@example.com"},
        output={"ok": True},
        app_refs=[AppRef(app="slack", entity_type="channel", entity_id="C1", role="write")],
    ))
    return run


def test_ingest_persists_run_and_spans(ingestor):
    run = make_run()
    trace_id = ingestor.ingest(run)
    runs = ingestor.list_runs()
    assert len(runs) == 1
    assert runs[0]["trace_id"] == trace_id
    spans = ingestor.store.backend.query("SELECT * FROM trace_spans WHERE trace_id = ?", (trace_id,))
    assert len(spans) == 2


def test_ingest_is_idempotent(ingestor):
    run = make_run()
    ingestor.ingest(run)
    ingestor.ingest(run)
    assert len(ingestor.list_runs()) == 1
    spans = ingestor.store.backend.query("SELECT COUNT(*) AS c FROM trace_spans")
    assert spans[0]["c"] == 2


def test_payload_is_redacted_in_blob(ingestor):
    run = make_run()
    trace_id = ingestor.ingest(run)
    # The stored trajectory document must not contain the raw email anywhere.
    doc_row = ingestor.store.backend.query_one(
        "SELECT payload_hash FROM trace_runs WHERE trace_id = ?", (trace_id,)
    )
    doc_blob = ingestor.store.blobs.get_text(doc_row["payload_hash"])
    assert "alice@example.com" not in doc_blob
    assert "REDACTED_EMAIL" in doc_blob

    # The per span offloaded input blob is likewise scrubbed.
    span_row = ingestor.store.backend.query_one(
        "SELECT input_ref FROM trace_spans WHERE tool_name = 'slack.post'"
    )
    span_blob = ingestor.store.blobs.get_text(span_row["input_ref"])
    assert "alice@example.com" not in span_blob
    assert "REDACTED_EMAIL" in span_blob


def test_app_refs_indexed(ingestor):
    run = make_run()
    ingestor.ingest(run)
    touching = ingestor.spans_touching("slack", "channel", "C1")
    assert len(touching) == 1
    assert touching[0]["tool_name"] == "slack.post"


def test_load_round_trip(ingestor):
    run = make_run()
    trace_id = ingestor.ingest(run)
    loaded = ingestor.load(trace_id)
    assert loaded is not None
    assert loaded.trace_id == trace_id
    assert loaded.agent == "claude_code"
    assert len(loaded.spans) == 2


def test_load_missing_returns_none(ingestor):
    assert ingestor.load("trace_absent") is None


def test_list_runs_filtered_by_agent(ingestor):
    ingestor.ingest(TraceRun(agent="claude_code", started_at=t(0), task_ref="a"))
    ingestor.ingest(TraceRun(agent="codex", started_at=t(0), task_ref="b"))
    assert len(ingestor.list_runs(agent="claude_code")) == 1
    assert len(ingestor.list_runs()) == 2
