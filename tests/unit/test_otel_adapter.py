"""Tests for OpenTelemetry and OpenInference interoperability."""

from __future__ import annotations

from datetime import datetime

from ombench.timeutil import UTC
from ombench.traces.otel_adapter import from_otel_spans, to_otel_spans
from ombench.traces.schema import AppRef, SpanKind, SpanStatus, TraceRun, TraceSpan


def t(minute: int) -> datetime:
    return datetime(2026, 5, 14, 17, minute, 0, tzinfo=UTC)


def make_run() -> TraceRun:
    run = TraceRun(agent="claude_code", group_id="g1", started_at=t(0))
    run.add_span(TraceSpan(kind=SpanKind.AGENT, name="root", started_at=t(0), ended_at=t(5)))
    run.add_span(TraceSpan(
        kind=SpanKind.LLM, name="plan", model="claude-opus-4-8", tokens=1200,
        started_at=t(1), ended_at=t(2), input="plan the task", output="a plan",
        cost_usd=0.03,
    ))
    run.add_span(TraceSpan(
        kind=SpanKind.TOOL, name="slack.post", tool_name="slack.post",
        tool_args={"channel": "C1"}, started_at=t(3), ended_at=t(4),
        app_refs=[AppRef(app="slack", entity_type="channel", entity_id="C1", role="write")],
    ))
    return run


def test_export_to_openinference():
    run = make_run()
    spans = to_otel_spans(run)
    assert len(spans) == 3
    llm = next(s for s in spans if s["attributes"].get("llm.model_name"))
    assert llm["attributes"]["openinference.span.kind"] == "LLM"
    assert llm["attributes"]["llm.token_count.total"] == 1200
    assert llm["attributes"]["session.id"] == "g1"
    tool = next(s for s in spans if s["attributes"].get("tool.name"))
    assert tool["attributes"]["tool.name"] == "slack.post"


def test_round_trip_preserves_structure():
    run = make_run()
    spans = to_otel_spans(run)
    imported = from_otel_spans(spans, trace_id=run.trace_id, agent="claude_code", group_id="g1")
    assert len(imported.spans) == 3
    kinds = [s.kind for s in imported.spans]
    assert kinds == [SpanKind.AGENT, SpanKind.LLM, SpanKind.TOOL]
    llm = imported.spans_of(SpanKind.LLM)[0]
    assert llm.model == "claude-opus-4-8"
    assert llm.tokens == 1200
    assert llm.cost_usd == 0.03


def test_round_trip_preserves_app_refs():
    run = make_run()
    imported = from_otel_spans(to_otel_spans(run))
    tool = imported.spans_of(SpanKind.TOOL)[0]
    assert len(tool.app_refs) == 1
    assert tool.app_refs[0].entity_id == "C1"
    assert tool.app_refs[0].role == "write"


def test_custom_kind_survives_round_trip():
    # CORRECTION maps to CHAIN in OpenInference but is restored via the custom attr.
    run = TraceRun(agent="a", started_at=t(0))
    run.add_span(TraceSpan(kind=SpanKind.CORRECTION, name="user fixed it", started_at=t(0)))
    imported = from_otel_spans(to_otel_spans(run))
    assert imported.spans[0].kind == SpanKind.CORRECTION


def test_import_foreign_spans_without_ombench_attrs():
    # A span produced by other tooling, lacking ombench specific attributes.
    foreign = [
        {
            "span_id": "s1",
            "parent_id": None,
            "name": "retrieve",
            "start_time": "2026-05-14T17:00:00.000Z",
            "end_time": "2026-05-14T17:00:01.000Z",
            "status_code": "OK",
            "attributes": {
                "openinference.span.kind": "RETRIEVER",
                "input.value": "query text",
            },
        }
    ]
    run = from_otel_spans(foreign, agent="phoenix")
    assert run.spans[0].kind == SpanKind.RETRIEVER
    assert run.spans[0].input == "query text"


def test_extra_attributes_are_preserved():
    run = TraceRun(agent="a", started_at=t(0))
    run.add_span(TraceSpan(
        kind=SpanKind.AGENT, name="root", started_at=t(0),
        attributes={"graph.node.id": "planner_0", "custom.flag": True},
    ))
    imported = from_otel_spans(to_otel_spans(run))
    assert imported.spans[0].attributes["graph.node.id"] == "planner_0"
    assert imported.spans[0].attributes["custom.flag"] is True


def test_unset_status_round_trips():
    run = TraceRun(agent="a", started_at=t(0))
    run.add_span(TraceSpan(kind=SpanKind.AGENT, name="root", started_at=t(0),
                           status=SpanStatus.UNSET))
    imported = from_otel_spans(to_otel_spans(run))
    assert imported.spans[0].status == SpanStatus.UNSET


def test_structured_input_and_tool_args_round_trip():
    run = TraceRun(agent="a", started_at=t(0))
    run.add_span(TraceSpan(kind=SpanKind.TOOL, name="t", tool_name="slack.post",
                           tool_args={"channel": "C1", "n": 3},
                           input={"channel": "C1"}, started_at=t(0)))
    imported = from_otel_spans(to_otel_spans(run))
    span = imported.spans_of(SpanKind.TOOL)[0]
    assert span.input == {"channel": "C1"}
    assert span.tool_args == {"channel": "C1", "n": 3}
