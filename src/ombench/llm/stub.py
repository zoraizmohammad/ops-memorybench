"""Deterministic stub LLM.

The stub is a scripted policy that stands in for a real model so the whole backtest
runs keyless and reproducibly. Crucially, its behavior is conditioned on the system
prompt: when the compiled knowledge base is mounted there, the stub reads directives
out of it and acts on them; when memory is absent it falls back to defaults. That is
what lets the deterministic path actually demonstrate whether memory helps, rather
than being a fixed policy that ignores the manipulation under test.

The stub is intentionally simple and transparent. It scans the mounted memory text
for cues relevant to the task (a preferred time, a target channel, a naming
convention, an approver) and emits the corresponding tool call. Without those cues it
emits a plausible but uninformed default. The eval rubric then scores the difference.
"""

from __future__ import annotations

import re

from .base import (
    LLMClient,
    LLMResponse,
    Message,
    Role,
    StopReason,
    ToolCall,
    ToolSpec,
)


def _count_tokens(text: str) -> int:
    # A cheap deterministic token proxy: words plus punctuation groups.
    return max(1, len(text.split()))


class StubLLM(LLMClient):
    """A deterministic, memory aware scripted agent.

    The stub plays a single assistant turn that either calls one tool (the action the
    task asks for) or answers in text. It returns ``END_TURN`` after acting so the
    agent loop terminates deterministically.
    """

    model = "stub"

    def __init__(self) -> None:
        self._step = 0

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        tools = tools or []
        task = self._latest_user_text(messages)
        memory = self._extract_memory(system)
        already_acted = any(m.tool_results for m in messages)

        input_tokens = _count_tokens(system) + sum(_count_tokens(m.content) for m in messages)

        # After a tool has run, wrap up with a short confirmation.
        if already_acted:
            return LLMResponse(
                text="Done. I completed the requested operation.",
                stop_reason=StopReason.END_TURN,
                input_tokens=input_tokens,
                output_tokens=8,
                model=self.model,
            )

        call = self._decide(task, memory, tools)
        if call is None:
            return LLMResponse(
                text="I could not determine an action for this task.",
                stop_reason=StopReason.END_TURN,
                input_tokens=input_tokens,
                output_tokens=10,
                model=self.model,
            )
        return LLMResponse(
            tool_calls=[call],
            stop_reason=StopReason.TOOL_USE,
            input_tokens=input_tokens,
            output_tokens=20,
            model=self.model,
        )

    # -- helpers ----------------------------------------------------------

    def _latest_user_text(self, messages: list[Message]) -> str:
        for m in reversed(messages):
            if m.role == Role.USER and m.content:
                return m.content
        return ""

    def _extract_memory(self, system: str) -> str:
        """Pull the mounted memory section out of the system prompt, if present."""
        marker = "Relevant memory"
        idx = system.find(marker)
        if idx == -1:
            # The whole system prompt may be the knowledge base in mounted-file mode.
            return system if "# file" in system else ""
        return system[idx:]

    def _decide(self, task: str, memory: str, tools: list[ToolSpec]) -> ToolCall | None:
        """Choose a tool call from the task and the available memory."""
        tool_names = {t.name for t in tools}
        task_l = task.lower()
        mem_l = memory.lower()

        # Reschedule a meeting: pick the time from memory if a preference exists.
        if "reschedule" in task_l or ("1:1" in task_l and "calendar" in " ".join(tool_names)):
            if "gcal.update_event" in tool_names:
                start = self._preferred_time(mem_l)
                return ToolCall(
                    id=self._next_id(),
                    name="gcal.update_event",
                    arguments={"event_id": self._guess_event(task), "start": start},
                )

        # Announce something in Slack: pick the channel from memory if known.
        if "announce" in task_l or "post" in task_l:
            if "slack.post_message" in tool_names:
                channel = self._preferred_channel(mem_l, task_l)
                text = self._announcement_text(mem_l, task)
                return ToolCall(
                    id=self._next_id(),
                    name="slack.post_message",
                    arguments={"channel": channel, "text": text},
                )

        # Create a document: apply a naming convention from memory if present.
        if "create" in task_l and ("doc" in task_l or "document" in task_l):
            if "gdocs.create_document" in tool_names:
                name = self._doc_name(mem_l, task)
                return ToolCall(
                    id=self._next_id(),
                    name="gdocs.create_document",
                    arguments={"name": name},
                )

        # Fall back to the first available tool with empty args, if any.
        if tools:
            return ToolCall(id=self._next_id(), name=tools[0].name, arguments={})
        return None

    def _next_id(self) -> str:
        self._step += 1
        return f"stubcall_{self._step}"

    # -- memory driven decisions -----------------------------------------

    def _preferred_time(self, mem: str) -> str:
        # If memory says afternoons, pick 3pm; if mornings, 9am; else a neutral default.
        if "afternoon" in mem:
            return "15:00"
        if "morning" in mem:
            return "09:00"
        return "12:00"  # uninformed default

    def _preferred_channel(self, mem: str, task: str) -> str:
        # Memory may name an announcements channel or convention.
        if "announcements channel" in mem or "announcements" in mem:
            return "announcements"
        # Without memory, default to a generic channel.
        return "general"

    def _announcement_text(self, mem: str, task: str) -> str:
        # Apply a stored format like "Launch <name> is live" if memory has it.
        name = self._project_name(task)
        if "is live" in mem and "launch" in mem:
            return f"Launch {name} is live"
        return f"Announcing {name}"

    def _doc_name(self, mem: str, task: str) -> str:
        subject = self._project_name(task)
        if "customer" in mem and "named" in mem:
            return f"Customer {subject} 2026-05-20"
        return subject

    def _project_name(self, task: str) -> str:
        # The project name is a capitalized word that is not a leading command verb.
        skip = {"announce", "post", "create", "reschedule", "draft", "send", "the", "a", "an", "my"}
        for word in re.findall(r"\b([A-Za-z][a-z]+)\b", task):
            if word.lower() in skip:
                continue
            if word[0].isupper():
                return word
        return "Update"

    def _guess_event(self, task: str) -> str:
        if "bob" in task.lower():
            return "ev_1on1_bob"
        return "ev_unknown"
