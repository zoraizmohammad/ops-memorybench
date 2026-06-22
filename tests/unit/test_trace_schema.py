"""Tests for the agent agnostic trajectory schema."""

from __future__ import annotations

from datetime import datetime

from ombench.timeutil import UTC
from ombench.traces.schema import (
    AppRef,
    MemoryCandidate,
    SpanKind,
    SpanStatus,
    TraceRun,
    TraceSpan,
)


def t(minute: int) -> datetime:
    return datetime(2026, 5, 14, 17, minute, 0, tzinfo=UTC)


def test_span_id_is_derived_and_deterministic():
    a = TraceSpan(kind=SpanKind.TOOL, name="slack.post", tool_name="slack.post",
                  started_at=t(0), input={"channel": "C1"})
    b = TraceSpan(kind=SpanKind.TOOL, name="slack.post", tool_name="slack.post",
                  started_at=t(0), input={"channel": "C1"})
    assert a.span_id == b.span_id
    assert a.span_id.startswith("span_")


def test_trace_id_derived():
    run = TraceRun(agent="claude_code", group_id="g1", started_at=t(0), task_ref="task1")
    assert run.trace_id.startswith("trace_")


def test_duration_seconds():
    span = TraceSpan(kind=SpanKind.LLM, started_at=t(0), ended_at=t(1))
    assert span.duration_seconds == 60.0


def test_duration_none_without_times():
    span = TraceSpan(kind=SpanKind.LLM)
    assert span.duration_seconds is None


def test_add_span_and_filter_by_kind():
    run = TraceRun(agent="codex", started_at=t(0))
    run.add_span(TraceSpan(kind=SpanKind.AGENT, name="root", started_at=t(0)))
    run.add_span(TraceSpan(kind=SpanKind.TOOL, name="tool", tool_name="x", started_at=t(1)))
    run.add_span(TraceSpan(kind=SpanKind.TOOL, name="tool2", tool_name="y", started_at=t(2)))
    assert len(run.spans_of(SpanKind.TOOL)) == 2
    assert len(run.spans_of(SpanKind.AGENT)) == 1


def test_collect_app_refs_and_candidates():
    run = TraceRun(agent="claude_code", started_at=t(0))
    run.add_span(TraceSpan(
        kind=SpanKind.TOOL, tool_name="slack.post", started_at=t(0),
        app_refs=[AppRef(app="slack", entity_type="channel", entity_id="C1", role="write")],
        memory_candidates=[MemoryCandidate(text="user prefers afternoons", kind="semantic")],
    ))
    refs = run.all_app_refs()
    assert refs[0].entity_id == "C1"
    cands = run.all_memory_candidates()
    assert cands[0].kind == "semantic"


def test_content_hash_stable():
    run1 = TraceRun(trace_id="fixed", agent="a", started_at=t(0))
    run2 = TraceRun(trace_id="fixed", agent="a", started_at=t(0))
    assert run1.content_hash == run2.content_hash


def test_times_coerced_to_utc():
    naive = datetime(2026, 5, 14, 17, 0, 0)
    run = TraceRun(agent="a", started_at=naive)
    assert run.started_at.tzinfo == UTC
    span = TraceSpan(kind=SpanKind.LLM, started_at=naive, ended_at=naive)
    assert span.started_at.tzinfo == UTC


def test_redactions_recorded():
    span = TraceSpan(kind=SpanKind.LLM, started_at=t(0), redactions=["email", "phone"])
    assert "email" in span.redactions


def test_default_status_ok():
    span = TraceSpan(kind=SpanKind.TOOL)
    assert span.status == SpanStatus.OK
