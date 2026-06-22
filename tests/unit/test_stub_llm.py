"""Tests for the deterministic stub LLM."""

from __future__ import annotations

from ombench.llm.base import Message, Role, StopReason, ToolSpec
from ombench.llm.stub import StubLLM

RESCHEDULE_TOOLS = [
    ToolSpec(name="gcal.update_event", description="update", input_schema={}),
]
ANNOUNCE_TOOLS = [
    ToolSpec(name="slack.post_message", description="post", input_schema={}),
]


def _msg(text):
    return [Message(role=Role.USER, content=text)]


def test_reschedule_uses_afternoon_from_memory():
    stub = StubLLM()
    system = "# Relevant memory\n- user prefers afternoons and avoids Fridays"
    resp = stub.complete(system=system, messages=_msg("Reschedule my 1:1 with Bob"),
                         tools=RESCHEDULE_TOOLS)
    assert resp.wants_tool
    call = resp.tool_calls[0]
    assert call.name == "gcal.update_event"
    assert call.arguments["start"] == "15:00"
    assert call.arguments["event_id"] == "ev_1on1_bob"


def test_reschedule_without_memory_uses_default():
    stub = StubLLM()
    resp = stub.complete(system="You are an assistant.", messages=_msg("Reschedule my 1:1 with Bob"),
                         tools=RESCHEDULE_TOOLS)
    call = resp.tool_calls[0]
    # No preference in memory, so the uninformed noon default.
    assert call.arguments["start"] == "12:00"


def test_announce_uses_channel_from_memory():
    stub = StubLLM()
    system = "# Relevant memory\n- Announce launches in the announcements channel using Launch <name> is live"
    resp = stub.complete(system=system, messages=_msg("Announce the Redwood launch"),
                         tools=ANNOUNCE_TOOLS)
    call = resp.tool_calls[0]
    assert call.name == "slack.post_message"
    assert call.arguments["channel"] == "announcements"
    assert "Launch Redwood is live" == call.arguments["text"]


def test_announce_without_memory_uses_default_channel():
    stub = StubLLM()
    resp = stub.complete(system="You are an assistant.", messages=_msg("Announce the Redwood launch"),
                         tools=ANNOUNCE_TOOLS)
    call = resp.tool_calls[0]
    assert call.arguments["channel"] == "general"
    assert call.arguments["text"] == "Announcing Redwood"


def test_wraps_up_after_tool_result():
    stub = StubLLM()
    messages = [
        Message(role=Role.USER, content="Reschedule my 1:1 with Bob"),
        Message(role=Role.ASSISTANT, content=""),
        Message(role=Role.USER, tool_results=[{"tool_call_id": "x", "content": "{\"ok\": true}"}]),
    ]
    resp = stub.complete(system="# Relevant memory", messages=messages, tools=RESCHEDULE_TOOLS)
    assert resp.stop_reason == StopReason.END_TURN
    assert "completed" in resp.text.lower()


def test_deterministic_across_runs():
    system = "# Relevant memory\n- user prefers afternoons"
    a = StubLLM().complete(system=system, messages=_msg("Reschedule my 1:1 with Bob"), tools=RESCHEDULE_TOOLS)
    b = StubLLM().complete(system=system, messages=_msg("Reschedule my 1:1 with Bob"), tools=RESCHEDULE_TOOLS)
    assert a.tool_calls[0].arguments == b.tool_calls[0].arguments


def test_token_usage_reported():
    resp = StubLLM().complete(system="some system text here", messages=_msg("a task"), tools=ANNOUNCE_TOOLS)
    assert resp.input_tokens > 0
    assert resp.output_tokens > 0


def test_no_tools_returns_text():
    resp = StubLLM().complete(system="x", messages=_msg("do something"), tools=[])
    assert resp.stop_reason == StopReason.END_TURN
    assert resp.tool_calls == []
