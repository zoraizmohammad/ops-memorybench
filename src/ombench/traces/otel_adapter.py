"""OpenTelemetry and OpenInference interoperability.

The trajectory format is provider neutral, but it earns that claim only if it maps
cleanly to and from the de facto standards. This module converts between an ombench
:class:`TraceRun` and a list of OpenTelemetry style span dicts that follow the
OpenInference semantic conventions (``openinference.span.kind``, ``llm.*``,
``tool.*``, ``retrieval.*``, ``input.value``, ``output.value``, ``session.id`` and
so on).

Two directions are supported:

- :func:`to_otel_spans` exports an ombench run to OpenInference span dicts, suitable
  for sending to any OTel compatible backend such as LangSmith, Weave, or Phoenix.
- :func:`from_otel_spans` imports OpenInference span dicts into an ombench run, so
  trajectories captured by other tooling can flow into the history substrate.

Keeping the mapping explicit and tested is what lets ombench sit alongside existing
observability stacks rather than replacing them.
"""

from __future__ import annotations

from typing import Any

from ..ids import canonical_json
from ..timeutil import from_iso, to_iso
from .schema import AppRef, SpanKind, SpanStatus, TraceRun, TraceSpan

# Map ombench span kinds to OpenInference span.kind values. OpenInference does not
# define USER or CORRECTION, so those round trip through a custom attribute.
_KIND_TO_OI = {
    SpanKind.AGENT: "AGENT",
    SpanKind.LLM: "LLM",
    SpanKind.TOOL: "TOOL",
    SpanKind.RETRIEVER: "RETRIEVER",
    SpanKind.EVALUATOR: "EVALUATOR",
    SpanKind.GUARDRAIL: "GUARDRAIL",
    SpanKind.HANDOFF: "AGENT",
    SpanKind.CHAIN: "CHAIN",
    SpanKind.USER: "CHAIN",
    SpanKind.CORRECTION: "CHAIN",
}
_OI_TO_KIND = {
    "AGENT": SpanKind.AGENT,
    "LLM": SpanKind.LLM,
    "TOOL": SpanKind.TOOL,
    "RETRIEVER": SpanKind.RETRIEVER,
    "EVALUATOR": SpanKind.EVALUATOR,
    "GUARDRAIL": SpanKind.GUARDRAIL,
    "CHAIN": SpanKind.CHAIN,
}

# Attribute used to preserve the precise ombench kind across a round trip.
_OMBENCH_KIND_ATTR = "ombench.span.kind"


def _value_str(value: Any) -> str:
    """Render an input or output value as a string for ``*.value`` attributes."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return canonical_json(value)


def to_otel_spans(run: TraceRun) -> list[dict[str, Any]]:
    """Export an ombench run to OpenInference style OTel span dicts."""
    out: list[dict[str, Any]] = []
    for span in run.spans:
        attrs: dict[str, Any] = dict(span.attributes)
        attrs["openinference.span.kind"] = _KIND_TO_OI[span.kind]
        attrs[_OMBENCH_KIND_ATTR] = span.kind.value
        attrs.setdefault("session.id", run.group_id or run.trace_id)

        if span.input is not None:
            attrs["input.value"] = _value_str(span.input)
        if span.output is not None:
            attrs["output.value"] = _value_str(span.output)
        if span.kind == SpanKind.LLM and span.model:
            attrs["llm.model_name"] = span.model
        if span.tokens is not None:
            attrs["llm.token_count.total"] = span.tokens
        if span.tool_name:
            attrs["tool.name"] = span.tool_name
        if span.tool_args is not None:
            attrs["tool.parameters"] = canonical_json(span.tool_args)
        if span.app_refs:
            attrs["ombench.app_refs"] = canonical_json(
                [r.model_dump() for r in span.app_refs]
            )
        if span.cost_usd is not None:
            attrs["ombench.cost_usd"] = span.cost_usd

        out.append(
            {
                "span_id": span.span_id,
                "parent_id": span.parent_id,
                "name": span.name or span.kind.value,
                "trace_id": run.trace_id,
                "start_time": to_iso(span.started_at) if span.started_at else None,
                "end_time": to_iso(span.ended_at) if span.ended_at else None,
                "status_code": "OK" if span.status == SpanStatus.OK else span.status.value.upper(),
                "attributes": attrs,
            }
        )
    return out


def from_otel_spans(
    spans: list[dict[str, Any]],
    *,
    trace_id: str | None = None,
    agent: str = "imported",
    group_id: str | None = None,
) -> TraceRun:
    """Import OpenInference style OTel span dicts into an ombench run."""
    run = TraceRun(
        trace_id=trace_id or "",
        agent=agent,
        group_id=group_id,
        workflow_name="imported",
    )
    for raw in spans:
        attrs = dict(raw.get("attributes", {}))
        kind = _resolve_kind(attrs)
        app_refs = _resolve_app_refs(attrs)
        status = (
            SpanStatus.OK
            if str(raw.get("status_code", "OK")).upper() == "OK"
            else SpanStatus.ERROR
        )
        tokens = attrs.get("llm.token_count.total")
        span = TraceSpan(
            span_id=raw.get("span_id", ""),
            parent_id=raw.get("parent_id"),
            kind=kind,
            name=raw.get("name"),
            started_at=from_iso(raw["start_time"]) if raw.get("start_time") else None,
            ended_at=from_iso(raw["end_time"]) if raw.get("end_time") else None,
            status=status,
            input=attrs.get("input.value"),
            output=attrs.get("output.value"),
            tool_name=attrs.get("tool.name"),
            model=attrs.get("llm.model_name"),
            tokens=int(tokens) if tokens is not None else None,
            cost_usd=attrs.get("ombench.cost_usd"),
            app_refs=app_refs,
            attributes={
                k: v
                for k, v in attrs.items()
                if not _is_mapped_attr(k)
            },
        )
        run.add_span(span)
    return run


def _resolve_kind(attrs: dict[str, Any]) -> SpanKind:
    if _OMBENCH_KIND_ATTR in attrs:
        try:
            return SpanKind(attrs[_OMBENCH_KIND_ATTR])
        except ValueError:
            pass
    oi = attrs.get("openinference.span.kind", "CHAIN")
    return _OI_TO_KIND.get(oi, SpanKind.CHAIN)


def _resolve_app_refs(attrs: dict[str, Any]) -> list[AppRef]:
    raw = attrs.get("ombench.app_refs")
    if not raw:
        return []
    import json

    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [AppRef(**item) for item in items]


_MAPPED_ATTRS = {
    "openinference.span.kind",
    _OMBENCH_KIND_ATTR,
    "input.value",
    "output.value",
    "llm.model_name",
    "llm.token_count.total",
    "tool.name",
    "tool.parameters",
    "ombench.app_refs",
    "ombench.cost_usd",
}


def _is_mapped_attr(key: str) -> bool:
    return key in _MAPPED_ATTRS
