"""Converters from concrete agent session transcripts to ombench trajectories.

The trajectory format is agent agnostic, so capture works by converting each
agent's native transcript into a :class:`TraceRun`. Two converters ship here:

- :func:`from_claude_code_session` reads Claude Code JSONL transcript lines, where
  each line is a message with a role and a content list that may contain text,
  ``tool_use`` blocks, and ``tool_result`` blocks.
- :func:`from_codex_session` reads a Codex style session object with an ``items``
  list of message and function call records.

Both produce the same :class:`TraceRun` shape, which is the point: downstream
ingestion, memory compilation, and backtesting never need to know which agent the
trajectory came from. App references are inferred from tool names and arguments via
:func:`infer_app_refs` so the trajectory links to SaaS entities even when the source
transcript does not annotate them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..timeutil import from_epoch, from_iso
from .schema import AppRef, SpanKind, SpanStatus, TraceRun, TraceSpan

# Tool name prefixes that indicate which SaaS app a tool call touches, and the
# argument keys that carry entity ids for each app.
_APP_PREFIXES = {
    "slack": "slack",
    "gcal": "gcal",
    "calendar": "gcal",
    "gdocs": "gdocs",
    "docs": "gdocs",
    "drive": "drive",
    "gmail": "gmail",
}
_ENTITY_ARG_KEYS = {
    "channel": ("slack", "channel"),
    "channel_id": ("slack", "channel"),
    "event_id": ("gcal", "event"),
    "calendar_id": ("gcal", "calendar"),
    "document_id": ("gdocs", "document"),
    "doc_id": ("gdocs", "document"),
    "file_id": ("drive", "file"),
}
# Tool name fragments that imply a write rather than a read.
_WRITE_HINTS = ("post", "create", "update", "send", "delete", "insert", "move", "set", "add")


def _parse_time(value: Any):
    """Parse a timestamp that may be ISO 8601 or epoch seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return from_epoch(value)
    try:
        return from_iso(str(value))
    except ValueError:
        return None


def infer_app_refs(tool_name: str, args: dict[str, Any]) -> list[AppRef]:
    """Infer SaaS entity references from a tool call.

    The app is taken from the tool name prefix; entity ids are read from known
    argument keys. The role is a write when the tool name suggests a mutation.
    """
    lower = tool_name.lower()
    role = "write" if any(h in lower for h in _WRITE_HINTS) else "read"
    refs: list[AppRef] = []
    for key, (app, entity_type) in _ENTITY_ARG_KEYS.items():
        if key in args and args[key]:
            refs.append(
                AppRef(app=app, entity_type=entity_type, entity_id=str(args[key]), role=role)
            )
    return refs


def _tool_span(
    *,
    tool_name: str,
    args: dict[str, Any],
    result: Any,
    parent_id: str | None,
    started_at=None,
    ended_at=None,
    status: SpanStatus = SpanStatus.OK,
) -> TraceSpan:
    return TraceSpan(
        kind=SpanKind.TOOL,
        name=tool_name,
        tool_name=tool_name,
        tool_args=args,
        parent_id=parent_id,
        input=args,
        output=result,
        started_at=started_at,
        ended_at=ended_at,
        status=status,
        app_refs=infer_app_refs(tool_name, args),
    )


def from_claude_code_session(
    lines: list[dict[str, Any]] | str | Path,
    *,
    group_id: str | None = None,
) -> TraceRun:
    """Convert Claude Code JSONL transcript lines into a :class:`TraceRun`.

    ``lines`` may be a list of already parsed dicts, a path to a ``.jsonl`` file, or
    a raw JSONL string. Each user and assistant message becomes a span; ``tool_use``
    blocks become TOOL spans paired with their ``tool_result`` output.
    """
    records = _load_jsonl(lines)
    run = TraceRun(agent="claude_code", group_id=group_id, workflow_name="operational_assistant")
    root = run.add_span(TraceSpan(kind=SpanKind.AGENT, name="claude_code_session"))

    # Pending tool_use blocks awaiting their matching tool_result by id.
    pending: dict[str, TraceSpan] = {}
    first_ts = None
    last_ts = None

    for rec in records:
        role = rec.get("role") or rec.get("type")
        ts = _parse_time(rec.get("timestamp") or rec.get("ts"))
        if ts:
            first_ts = first_ts or ts
            last_ts = ts
        content = rec.get("content")
        blocks = _as_blocks(content)

        for block in blocks:
            btype = block.get("type")
            if btype == "tool_use":
                tool_name = block.get("name", "tool")
                args = block.get("input", {}) or {}
                span = _tool_span(
                    tool_name=tool_name, args=args, result=None,
                    parent_id=root.span_id, started_at=ts,
                )
                run.add_span(span)
                tool_id = block.get("id")
                if tool_id:
                    pending[tool_id] = span
            elif btype == "tool_result":
                tool_id = block.get("tool_use_id")
                span = pending.pop(tool_id, None)
                if span is not None:
                    # Replace the placeholder span with one carrying the result.
                    idx = run.spans.index(span)
                    is_error = bool(block.get("is_error"))
                    run.spans[idx] = _tool_span(
                        tool_name=span.tool_name,
                        args=span.tool_args or {},
                        result=_block_text(block),
                        parent_id=root.span_id,
                        started_at=span.started_at,
                        ended_at=ts,
                        status=SpanStatus.ERROR if is_error else SpanStatus.OK,
                    )
            elif btype == "text" and role == "user":
                run.add_span(TraceSpan(
                    kind=SpanKind.USER, name="user_message", parent_id=root.span_id,
                    input=block.get("text", ""), started_at=ts,
                ))
            elif btype == "text" and role == "assistant":
                run.add_span(TraceSpan(
                    kind=SpanKind.LLM, name="assistant_message", parent_id=root.span_id,
                    output=block.get("text", ""), started_at=ts,
                ))

    run.started_at = first_ts
    run.ended_at = last_ts
    return run


def from_codex_session(
    session: dict[str, Any] | str | Path,
    *,
    group_id: str | None = None,
) -> TraceRun:
    """Convert a Codex style session object into a :class:`TraceRun`.

    ``session`` may be a dict, a path to a JSON file, or a JSON string. The session
    has an ``items`` list whose entries are ``message`` records (with ``role`` and
    ``content``) and ``function_call`` records (with ``name``, ``arguments``, and an
    ``output``).
    """
    obj = _load_json(session)
    run = TraceRun(
        agent="codex",
        group_id=group_id or obj.get("id"),
        workflow_name="operational_assistant",
    )
    root = run.add_span(TraceSpan(kind=SpanKind.AGENT, name="codex_session"))

    first_ts = None
    last_ts = None
    for item in obj.get("items", []):
        itype = item.get("type")
        ts = _parse_time(item.get("timestamp"))
        if ts:
            first_ts = first_ts or ts
            last_ts = ts
        if itype == "message":
            role = item.get("role")
            text = _coerce_text(item.get("content"))
            if role == "user":
                run.add_span(TraceSpan(
                    kind=SpanKind.USER, name="user_message", parent_id=root.span_id,
                    input=text, started_at=ts,
                ))
            else:
                run.add_span(TraceSpan(
                    kind=SpanKind.LLM, name="assistant_message", parent_id=root.span_id,
                    output=text, started_at=ts,
                ))
        elif itype in ("function_call", "tool_call"):
            tool_name = item.get("name", "tool")
            args = _coerce_args(item.get("arguments"))
            run.add_span(_tool_span(
                tool_name=tool_name, args=args, result=item.get("output"),
                parent_id=root.span_id, started_at=ts, ended_at=ts,
            ))

    run.started_at = first_ts
    run.ended_at = last_ts
    return run


# -- helpers --------------------------------------------------------------


def _load_jsonl(source: list[dict[str, Any]] | str | Path) -> list[dict[str, Any]]:
    if isinstance(source, list):
        return source
    text = Path(source).read_text(encoding="utf-8") if _is_path(source) else str(source)
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _load_json(source: dict[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(source, dict):
        return source
    text = Path(source).read_text(encoding="utf-8") if _is_path(source) else str(source)
    return json.loads(text)


def _is_path(source: Any) -> bool:
    if isinstance(source, Path):
        return True
    if isinstance(source, str) and "\n" not in source and source.endswith((".json", ".jsonl")):
        return True
    return False


def _as_blocks(content: Any) -> list[dict[str, Any]]:
    """Normalize message content into a list of typed blocks."""
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, dict):
        return [content]
    if isinstance(content, list):
        blocks: list[dict[str, Any]] = []
        for item in content:
            if isinstance(item, str):
                blocks.append({"type": "text", "text": item})
            elif isinstance(item, dict):
                blocks.append(item)
        return blocks
    return []


def _block_text(block: dict[str, Any]) -> Any:
    content = block.get("content")
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict)]
        return "".join(parts)
    return content


def _coerce_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return str(content) if content is not None else ""


def _coerce_args(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except (TypeError, ValueError):
            return {"raw": arguments}
    return {}
