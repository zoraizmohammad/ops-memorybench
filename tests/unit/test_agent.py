"""Tests for the operational agent under test."""

from __future__ import annotations

from ombench.llm.agent import OperationalAgent
from ombench.llm.base import ToolSpec
from ombench.llm.stub import StubLLM
from ombench.traces.schema import AppRef, SpanKind

RESCHEDULE_TOOLS = [
    ToolSpec(name="gcal.update_event", description="update a calendar event",
             input_schema={"type": "object"}),
]


def make_executor(record):
    def executor(name, args):
        record.append((name, args))
        refs = [AppRef(app="gcal", entity_type="event",
                       entity_id=args.get("event_id", "?"), role="write")]
        return {"ok": True}, refs
    return executor


def test_agent_runs_tool_loop_and_records_trajectory():
    record = []
    agent = OperationalAgent(
        StubLLM(), tools=RESCHEDULE_TOOLS, tool_executor=make_executor(record),
        memory_text="# Relevant memory\n- user prefers afternoons",
    )
    result = agent.run("Reschedule my 1:1 with Bob")
    # The tool was executed once with the afternoon time from memory.
    assert len(record) == 1
    assert record[0][0] == "gcal.update_event"
    assert record[0][1]["start"] == "15:00"
    # The trajectory has agent, user, llm, and tool spans.
    kinds = {s.kind for s in result.trace.spans}
    assert SpanKind.TOOL in kinds
    assert SpanKind.LLM in kinds


def test_agent_terminates_on_end_turn():
    agent = OperationalAgent(
        StubLLM(), tools=RESCHEDULE_TOOLS, tool_executor=make_executor([]),
        memory_text="# Relevant memory\n- user prefers afternoons",
    )
    result = agent.run("Reschedule my 1:1 with Bob")
    # After the tool runs, the stub wraps up and the loop ends.
    assert "completed" in result.final_text.lower()
    assert result.steps <= agent.max_steps


def test_memory_changes_behavior():
    # With afternoon memory vs without, the chosen time differs.
    rec_with = []
    OperationalAgent(StubLLM(), tools=RESCHEDULE_TOOLS, tool_executor=make_executor(rec_with),
                     memory_text="# Relevant memory\n- user prefers afternoons").run(
        "Reschedule my 1:1 with Bob")
    rec_without = []
    OperationalAgent(StubLLM(), tools=RESCHEDULE_TOOLS, tool_executor=make_executor(rec_without),
                     memory_text=None).run("Reschedule my 1:1 with Bob")
    assert rec_with[0][1]["start"] == "15:00"
    assert rec_without[0][1]["start"] == "12:00"


def test_system_prompt_mounts_memory():
    agent = OperationalAgent(StubLLM(), tools=[], tool_executor=make_executor([]),
                             memory_text="# Relevant memory\n- a fact")
    assert "a fact" in agent.system_prompt
    bare = OperationalAgent(StubLLM(), tools=[], tool_executor=make_executor([]))
    assert "Relevant memory" not in bare.system_prompt


def test_agent_records_token_usage():
    agent = OperationalAgent(StubLLM(), tools=RESCHEDULE_TOOLS, tool_executor=make_executor([]),
                             memory_text="# Relevant memory\n- user prefers afternoons")
    result = agent.run("Reschedule my 1:1 with Bob")
    assert result.input_tokens > 0
    assert result.output_tokens > 0


def test_agent_app_refs_recorded():
    agent = OperationalAgent(StubLLM(), tools=RESCHEDULE_TOOLS, tool_executor=make_executor([]),
                             memory_text="# Relevant memory\n- user prefers afternoons")
    result = agent.run("Reschedule my 1:1 with Bob")
    refs = result.trace.all_app_refs()
    assert any(r.app == "gcal" for r in refs)


def test_max_steps_bounds_loop():
    # An executor that never satisfies still terminates at max_steps if the model
    # kept calling tools. The stub stops after one tool, so use a tiny cap to assert
    # the bound is respected structurally.
    agent = OperationalAgent(StubLLM(), tools=RESCHEDULE_TOOLS, tool_executor=make_executor([]),
                             memory_text="# Relevant memory\n- user prefers afternoons", max_steps=1)
    result = agent.run("Reschedule my 1:1 with Bob")
    assert result.steps == 1
