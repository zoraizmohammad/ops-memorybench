"""Tests for Claude Code and Codex session converters."""

from __future__ import annotations

from pathlib import Path

from ombench.traces.converters import (
    from_claude_code_session,
    from_codex_session,
    infer_app_refs,
)
from ombench.traces.schema import SpanKind

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "trajectories"


def test_infer_app_refs_read_vs_write():
    read = infer_app_refs("gcal.get_event", {"event_id": "ev1"})
    assert read[0].app == "gcal"
    assert read[0].entity_type == "event"
    assert read[0].role == "read"

    write = infer_app_refs("gcal.update_event", {"event_id": "ev1"})
    assert write[0].role == "write"


def test_infer_app_refs_slack_channel():
    refs = infer_app_refs("slack.post_message", {"channel": "C1", "text": "hi"})
    assert refs[0].app == "slack"
    assert refs[0].entity_type == "channel"
    assert refs[0].entity_id == "C1"
    assert refs[0].role == "write"


def test_claude_code_conversion_from_file():
    run = from_claude_code_session(FIXTURES / "claude_code_reschedule.jsonl")
    assert run.agent == "claude_code"
    # Two tool calls, both with results paired in.
    tools = run.spans_of(SpanKind.TOOL)
    assert len(tools) == 2
    names = {s.tool_name for s in tools}
    assert names == {"gcal.get_event", "gcal.update_event"}
    # The update tool produced an app ref with write role.
    update = next(s for s in tools if s.tool_name == "gcal.update_event")
    assert update.app_refs[0].role == "write"
    assert update.output is not None  # result was paired


def test_claude_code_captures_user_and_assistant():
    run = from_claude_code_session(FIXTURES / "claude_code_reschedule.jsonl")
    users = run.spans_of(SpanKind.USER)
    assert any("afternoons" in (s.input or "") for s in users)
    assistants = run.spans_of(SpanKind.LLM)
    assert len(assistants) >= 1


def test_claude_code_start_end_times():
    run = from_claude_code_session(FIXTURES / "claude_code_reschedule.jsonl")
    assert run.started_at is not None
    assert run.ended_at is not None
    assert run.ended_at >= run.started_at


def test_codex_conversion_from_file():
    run = from_codex_session(FIXTURES / "codex_announce.json")
    assert run.agent == "codex"
    assert run.group_id == "codex_sess_announce_1"
    tools = run.spans_of(SpanKind.TOOL)
    assert len(tools) == 1
    assert tools[0].tool_name == "slack.post_message"
    # Channel ref inferred and marked write.
    assert tools[0].app_refs[0].entity_id == "C_launch_redwood"
    assert tools[0].app_refs[0].role == "write"


def test_codex_string_arguments_parsed():
    run = from_codex_session(FIXTURES / "codex_announce.json")
    tool = run.spans_of(SpanKind.TOOL)[0]
    assert tool.tool_args["channel"] == "C_launch_redwood"


def test_claude_code_from_list_of_dicts():
    records = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": [{"type": "text", "text": "hi there"}]},
    ]
    run = from_claude_code_session(records, group_id="g1")
    assert run.group_id == "g1"
    assert len(run.spans_of(SpanKind.USER)) == 1
    assert len(run.spans_of(SpanKind.LLM)) == 1


def test_both_agents_produce_same_shape():
    cc = from_claude_code_session(FIXTURES / "claude_code_reschedule.jsonl")
    cx = from_codex_session(FIXTURES / "codex_announce.json")
    # Same model type, both have an AGENT root and TOOL spans.
    assert cc.spans_of(SpanKind.AGENT)
    assert cx.spans_of(SpanKind.AGENT)
    assert type(cc) is type(cx)
