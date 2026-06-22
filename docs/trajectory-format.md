# Trajectory format

The trajectory format is agent agnostic but span based, closely aligned to
OpenTelemetry and the OpenInference semantic conventions so it maps cleanly to and
from existing observability stacks. Capture works by converting each agent's native
transcript into this one format; downstream ingestion, memory compilation, and
backtesting never need to know which agent produced a trajectory.

## Shape

- A `TraceRun` is one end to end agent job: identity (`trace_id`, `group_id`), the
  producing agent, lifecycle timestamps, user and task references, and an ordered list
  of spans.
- A `TraceSpan` is one operation: a kind (`AGENT`, `LLM`, `TOOL`, `RETRIEVER`,
  `EVALUATOR`, `GUARDRAIL`, `HANDOFF`, `CHAIN`, `USER`, `CORRECTION`), timing, status,
  input and output (inline or offloaded to the blob store by hash), tool details,
  token and cost, and an open attribute bag.

## Project specific enrichments

Beyond the standard span fields, the format carries what this project needs and
mainstream tracing treats as optional:

- **app state references** on tool spans, the join between a trajectory and SaaS state
- **memory candidate hints**, what the run suggests is worth remembering
- **redaction metadata**, so the privacy posture of a stored span is auditable
- **correction spans**, the signal that the user fixed something, which is among the
  strongest signals for mining a memory task

## Capture

The bundled Claude Code plugin (`plugin/ombench-capture`) registers command hooks on
`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, and `SessionEnd`. Each runs
`python -m ombench.traces.hook`, which accumulates session events incrementally and,
on session end, builds a trajectory preferring the full transcript and falling back to
the hook log. Capture is non blocking and never interrupts the agent.

## Interop

`ombench.traces.otel_adapter` exports a run to OpenInference span dicts and imports
foreign OTel spans back, so ombench sits alongside LangSmith, Weave, or Phoenix rather
than replacing them. Custom span kinds round trip through a private attribute.

## Privacy

The rule is to store enough to replay but not more than the privacy policy allows.
Payloads are redacted before storage (emails, phones, secrets, sensitive keys), raw
hidden chain of thought is never stored as first class memory, and large payloads are
offloaded to the content addressed blob store.
