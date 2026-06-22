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
        """Choose a tool call from the task and the available memory.

        The decision is a sequence of intent matchers. Each reads the task to find
        the intent and the mounted memory to find the directive that should shape the
        action. When memory lacks the directive, the stub falls back to an uninformed
        default, which is what makes the with versus without memory comparison
        meaningful.
        """
        names = {t.name for t in tools}
        task_l = task.lower()
        mem = memory.lower()

        # Triage a meeting decline: a standing rule may say optional attendees decline.
        if ("decline" in task_l or "optional" in task_l) and "gcal.respond_event" in names:
            response = "declined" if "optional attendees" in mem and "decline" in mem else "accepted"
            return ToolCall(self._next_id(), "gcal.respond_event",
                            {"event_id": self._guess_event(task), "response": response})

        # Schedule an external call: a timezone constraint may set the earliest time.
        if ("schedule" in task_l or "external call" in task_l) and "gcal.create_event" in names \
                and "reschedule" not in task_l:
            start = "10:00" if "before 10am" in mem or "10am pacific" in mem else "08:00"
            return ToolCall(self._next_id(), "gcal.create_event",
                            {"summary": f"Call {self._project_name(task)}", "start": start})

        # Create a travel itinerary: airline and seating preferences from memory.
        if "travel" in task_l or "itinerary" in task_l or "flight" in task_l:
            if "gcal.create_event" in names:
                airline = "United" if "united" in mem else "any"
                seat = "aisle" if "aisle" in mem else "any"
                return ToolCall(self._next_id(), "gcal.create_event",
                                {"summary": f"Travel airline {airline} seat {seat}"})

        # Reschedule a meeting: pick the time from memory if a preference exists.
        if ("reschedule" in task_l or "1:1" in task_l) and "gcal.update_event" in names:
            return ToolCall(self._next_id(), "gcal.update_event",
                            {"event_id": self._guess_event(task), "start": self._preferred_time(mem)})

        # Decide DM versus public, or handle a VIP contact: a person preference may
        # say to use a direct message instead of posting publicly.
        if ("dm" in task_l or "vip" in task_l or "reply" in task_l or "follow up with" in task_l) \
                and "slack.send_dm" in names:
            if "prefers direct messages" in mem or "personal reply" in mem or "high priority" in mem:
                return ToolCall(self._next_id(), "slack.send_dm",
                                {"user": self._guess_user(task), "text": "Following up personally."})

        # Route a request to a channel: a routing rule names the destination.
        if "route" in task_l and "slack.post_message" in names:
            channel = self._routing_channel(mem, task_l)
            return ToolCall(self._next_id(), "slack.post_message",
                            {"channel": channel, "text": "Routing your request."})

        # Announce or post: pick the channel and wording from memory if known.
        if ("announce" in task_l or "post" in task_l) and "slack.post_message" in names:
            return ToolCall(self._next_id(), "slack.post_message",
                            {"channel": self._preferred_channel(mem, task_l),
                             "text": self._announcement_text(mem, task)})

        # Invite the right approver: a signing chain names who must be tagged.
        if ("approver" in task_l or "invite" in task_l or "review" in task_l) and "gcal.create_event" in names:
            approver = "vp-product" if "vp of product" in mem or "approver" in mem else "team"
            return ToolCall(self._next_id(), "gcal.create_event",
                            {"summary": "Approval", "attendees": [approver]})

        # Prepare a weekly summary or draft meeting notes: a format/template applies.
        if ("summary" in task_l or "notes" in task_l or "weekly" in task_l) \
                and "gdocs.create_document" in names:
            body = self._document_body(mem, task_l)
            return ToolCall(self._next_id(), "gdocs.create_document",
                            {"name": self._doc_name(mem, task), "body": body})

        # Update a project page: a canonical source of truth doc names the target.
        if "update" in task_l and ("page" in task_l or "project" in task_l) and "gdocs.update_document" in names:
            doc = "doc_redwood_overview" if "canonical" in mem or "overview" in mem else "doc_unknown"
            return ToolCall(self._next_id(), "gdocs.update_document",
                            {"document_id": doc, "body": "Updated."})

        # Create or name a document: apply a naming convention from memory.
        if "create" in task_l and ("doc" in task_l or "document" in task_l) and "gdocs.create_document" in names:
            return ToolCall(self._next_id(), "gdocs.create_document",
                            {"name": self._doc_name(mem, task)})

        # Find a prior decision: cite it in text, respecting a do not reopen norm.
        if "decision" in task_l or "prior" in task_l or "scope" in task_l:
            cited = "Per the prior decision, scope is frozen." if "frozen" in mem or "do not reopen" in mem \
                else "I could not find a prior decision."
            return None if "slack.post_message" not in names else ToolCall(
                self._next_id(), "slack.post_message", {"channel": "general", "text": cited})

        # Fall back to the first available tool with empty args, if any.
        if tools:
            return ToolCall(self._next_id(), tools[0].name, {})
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
        if "weekly" in task.lower() or "summary" in task.lower():
            return f"Weekly Summary {subject}"
        return subject

    def _routing_channel(self, mem: str, task: str) -> str:
        # A routing taxonomy in memory maps request kinds to channels.
        if "bugs go to" in mem or "engineering" in mem:
            return "engineering"
        return "general"

    def _document_body(self, mem: str, task: str) -> str:
        # A team format may require metrics first or a specific section order.
        if "metric" in mem and "first" in mem:
            return "## Metrics\n## Highlights\n## Risks"
        if "section order" in mem or "template" in mem:
            return "## Attendees\n## Agenda\n## Decisions\n## Action Items"
        return "## Notes"

    def _guess_user(self, task: str) -> str:
        for name, uid in (("alice", "U_ALICE"), ("bob", "U_BOB"), ("carol", "U_CAROL")):
            if name in task.lower():
                return uid
        return "U_UNKNOWN"

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
