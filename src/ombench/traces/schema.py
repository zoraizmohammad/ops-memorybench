"""Agent agnostic trajectory schema.

A trajectory is one end to end agent job (a :class:`TraceRun`) made of nested
operations (:class:`TraceSpan`). The format is deliberately provider neutral but
span based so it maps cleanly to and from OpenTelemetry and OpenInference, OpenAI
Agents tracing, and Anthropic tool use traces, while carrying the extra fields this
project needs that mainstream tracing often treats as optional:

- app state references on tool spans, the join between a trajectory and SaaS state
- correction events, the signal that the user fixed something
- memory candidate hints, what the run suggests is worth remembering
- redaction metadata, so privacy handling is explicit
- replay contract hooks, so a span can be re executed deterministically

The design follows the guidance that you should store enough to replay but not more
than your privacy policy allows. Large inputs and outputs are offloaded to the blob
store and referenced by hash; raw hidden chain of thought is never stored as first
class memory, only compact summaries and selected evidence.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..ids import content_hash, new_id
from ..timeutil import ensure_utc


class SpanKind(StrEnum):
    """Span taxonomy, aligned to OpenInference and OpenAI Agents tracing.

    The kinds cover the operational breakdown of an agent run: the agent itself,
    model generations, tool and function calls, retrieval, evaluation, guardrails,
    handoffs between agents, and explicit user corrections which are central to
    mining memory worthy moments.
    """

    AGENT = "AGENT"
    LLM = "LLM"
    TOOL = "TOOL"
    RETRIEVER = "RETRIEVER"
    EVALUATOR = "EVALUATOR"
    GUARDRAIL = "GUARDRAIL"
    HANDOFF = "HANDOFF"
    CHAIN = "CHAIN"
    USER = "USER"
    CORRECTION = "CORRECTION"


class SpanStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    UNSET = "unset"


class AppRef(BaseModel):
    """A reference from a span to a SaaS entity.

    This is the structural link between trajectories and app state. When a tool
    span reads or writes a Slack channel or a Calendar event, the reference is
    recorded so the memory compiler and the benchmark miner can connect agent
    behavior to the entities it touched.
    """

    model_config = ConfigDict(frozen=True)

    app: str
    entity_type: str
    entity_id: str
    role: str = "read"  # read | write | mention


class MemoryCandidate(BaseModel):
    """A hint emitted during a run that something may be worth remembering.

    Candidates are not memory items. They are raw suggestions (an explicit user
    statement, a repeated correction, a discovered convention) that the memory
    compiler later scores, deduplicates, and possibly promotes into the knowledge
    base with provenance back to the span that produced them.
    """

    text: str
    kind: str = "semantic"  # episodic | semantic | procedural
    namespace: str = "user"  # user | team | project | app_state
    subject: str | None = None
    confidence_hint: float | None = None


class TraceSpan(BaseModel):
    """One operation within a run.

    Inputs and outputs are stored inline for small payloads and otherwise offloaded
    to the blob store via ``input_ref`` and ``output_ref``. ``attributes`` is an
    open bag for OpenInference style keys such as ``session.id`` and
    ``graph.node.id``. ``redactions`` lists what was removed from inputs or outputs
    so the privacy posture of the stored span is auditable.
    """

    span_id: str = ""
    parent_id: str | None = None
    kind: SpanKind
    name: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: SpanStatus = SpanStatus.OK

    # Small payloads live inline; large ones move to the blob store as refs.
    input: Any | None = None
    output: Any | None = None
    input_ref: str | None = None
    output_ref: str | None = None

    # Tool and model details.
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    model: str | None = None
    tokens: int | None = None
    cost_usd: float | None = None

    # Project specific enrichments.
    app_refs: list[AppRef] = Field(default_factory=list)
    memory_candidates: list[MemoryCandidate] = Field(default_factory=list)
    redactions: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if self.started_at is not None:
            object.__setattr__(self, "started_at", ensure_utc(self.started_at))
        if self.ended_at is not None:
            object.__setattr__(self, "ended_at", ensure_utc(self.ended_at))
        if not self.span_id:
            seed = {
                "kind": self.kind.value,
                "name": self.name,
                "parent_id": self.parent_id,
                "tool_name": self.tool_name,
                "started_at": self.started_at,
                "input": self.input,
            }
            object.__setattr__(self, "span_id", new_id("span", seed=seed))

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.ended_at:
            return (self.ended_at - self.started_at).total_seconds()
        return None


class TraceRun(BaseModel):
    """One end to end agent job.

    A run carries identity (``trace_id``, ``group_id``), provenance about which
    agent produced it, lifecycle timestamps, references to the user and task, and
    the ordered list of spans. ``trace_id`` is derived deterministically from the
    run's identity when not supplied so re ingesting the same session is idempotent.
    """

    model_config = ConfigDict(validate_assignment=True)

    trace_id: str = ""
    group_id: str | None = None
    workflow_name: str = "operational_assistant"
    agent: str = "unknown"  # claude_code | codex | ...
    started_at: datetime | None = None
    ended_at: datetime | None = None
    user_ref: str | None = None
    task_ref: str | None = None
    status: SpanStatus = SpanStatus.OK
    spans: list[TraceSpan] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if self.started_at is not None:
            object.__setattr__(self, "started_at", ensure_utc(self.started_at))
        if self.ended_at is not None:
            object.__setattr__(self, "ended_at", ensure_utc(self.ended_at))
        if not self.trace_id:
            seed = {
                "agent": self.agent,
                "workflow_name": self.workflow_name,
                "group_id": self.group_id,
                "started_at": self.started_at,
                "task_ref": self.task_ref,
            }
            object.__setattr__(self, "trace_id", new_id("trace", seed=seed))

    # -- convenience ------------------------------------------------------

    def add_span(self, span: TraceSpan) -> TraceSpan:
        self.spans.append(span)
        return span

    def spans_of(self, kind: SpanKind) -> list[TraceSpan]:
        return [s for s in self.spans if s.kind == kind]

    def all_app_refs(self) -> list[AppRef]:
        refs: list[AppRef] = []
        for span in self.spans:
            refs.extend(span.app_refs)
        return refs

    def all_memory_candidates(self) -> list[MemoryCandidate]:
        cands: list[MemoryCandidate] = []
        for span in self.spans:
            cands.extend(span.memory_candidates)
        return cands

    @property
    def content_hash(self) -> str:
        """Stable hash of the full trajectory for content addressed storage."""
        return content_hash(self.model_dump(mode="json"))
