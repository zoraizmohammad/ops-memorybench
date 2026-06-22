"""The operational agent under test.

A thin agent loop that drives an :class:`LLMClient` against a set of tools until the
model stops calling them, recording an ombench trajectory as it goes. This is the
agent the backtest evaluates: the same agent runs with and without the compiled
knowledge base mounted in its system prompt, and the rubric scores the difference.

Tools are executed by a ``tool_executor`` callable supplied by the caller, which is
where the replay sandbox plugs in. The loop is bounded by ``max_steps`` so a
misbehaving model cannot spin forever.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..ids import canonical_json
from ..timeutil import utcnow
from ..traces.schema import AppRef, SpanKind, TraceRun, TraceSpan
from .base import LLMClient, Message, Role, ToolSpec

# A tool executor takes a tool name and arguments and returns a result payload and
# the app references the call touched.
ToolExecutor = Callable[[str, dict[str, Any]], tuple[Any, list[AppRef]]]

DEFAULT_SYSTEM = (
    "You are an operational assistant that completes admin tasks over Slack, "
    "Google Calendar, and Google Docs. Use the available tools to take the single "
    "most appropriate action for the user's request, then stop."
)


@dataclass
class AgentResult:
    """The outcome of one agent run."""

    trace: TraceRun
    final_text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    steps: int = 0


class OperationalAgent:
    """Runs the tool loop for one task and records a trajectory."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        tools: list[ToolSpec],
        tool_executor: ToolExecutor,
        system: str = DEFAULT_SYSTEM,
        memory_text: str | None = None,
        max_steps: int = 6,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.tool_executor = tool_executor
        self.base_system = system
        self.memory_text = memory_text
        self.max_steps = max_steps

    @property
    def system_prompt(self) -> str:
        """The system prompt, with the knowledge base mounted when present.

        Mounting memory into the system prompt is exactly the manipulation the
        backtest measures: the with memory and without memory conditions differ only
        in whether this section is present.
        """
        if self.memory_text:
            return f"{self.base_system}\n\n{self.memory_text}"
        return self.base_system

    def run(self, task: str, *, user_ref: str | None = None, task_ref: str | None = None) -> AgentResult:
        """Run the agent on a task and return the result and trajectory."""
        run = TraceRun(
            agent="ombench_agent",
            workflow_name="operational_assistant",
            user_ref=user_ref,
            task_ref=task_ref,
            started_at=utcnow(),
        )
        root = run.add_span(TraceSpan(kind=SpanKind.AGENT, name="agent_run", started_at=utcnow()))
        run.add_span(TraceSpan(kind=SpanKind.USER, name="task", input=task, parent_id=root.span_id))

        messages: list[Message] = [Message(role=Role.USER, content=task)]
        result = AgentResult(trace=run, final_text="")

        for _step in range(self.max_steps):
            response = self.llm.complete(
                system=self.system_prompt, messages=messages, tools=self.tools
            )
            result.input_tokens += response.input_tokens
            result.output_tokens += response.output_tokens
            result.cost_usd += self.llm.cost_usd(response)
            result.steps += 1

            run.add_span(TraceSpan(
                kind=SpanKind.LLM, name="generation", model=self.llm.model,
                output=response.text, tokens=response.output_tokens,
                cost_usd=self.llm.cost_usd(response), started_at=utcnow(),
                parent_id=root.span_id,
            ))

            if not response.wants_tool:
                result.final_text = response.text
                break

            # Record the assistant tool-call turn, then execute each tool.
            messages.append(Message(role=Role.ASSISTANT, content=response.text, tool_calls=response.tool_calls))
            tool_results = []
            for call in response.tool_calls:
                output, app_refs = self.tool_executor(call.name, call.arguments)
                result.tool_calls.append({"name": call.name, "arguments": call.arguments, "output": output})
                run.add_span(TraceSpan(
                    kind=SpanKind.TOOL, name=call.name, tool_name=call.name,
                    tool_args=call.arguments, input=call.arguments, output=output,
                    app_refs=app_refs, started_at=utcnow(), parent_id=root.span_id,
                ))
                tool_results.append(
                    {"tool_call_id": call.id, "content": canonical_json(output)}
                )
            messages.append(Message(role=Role.USER, tool_results=tool_results))

        run.ended_at = utcnow()
        return result
