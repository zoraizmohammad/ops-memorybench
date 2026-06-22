"""Candidate extraction.

Turns history into raw memory candidates. Candidates are not yet knowledge; they are
suggestions that the scorer, resolver, and compiler later weigh, deduplicate, and
possibly promote into the knowledge base. Extraction draws from two sources:

- **trajectories**: explicit user statements ("I prefer", "always", "never",
  "remember that"), corrections (a USER turn after a tool action that fixes it), and
  repeated procedures (the same tool sequence recurring across runs).
- **app state**: durable conventions stated in messages and documents, for example a
  team naming convention or an announcement format.

The extractor is intentionally rule based and deterministic so the keyless path
produces stable candidates. An optional LLM backed extractor can be layered on top
later; the structured output it would produce is the same :class:`MemoryCandidate`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..events.store import EventStore
from ..traces.schema import MemoryCandidate, SpanKind, TraceRun

# Phrases that signal an explicit, durable statement worth remembering.
_PREFERENCE_PATTERNS = [
    re.compile(r"\bi (?:prefer|like|want|always|never)\b", re.IGNORECASE),
    re.compile(r"\b(?:please )?remember (?:that|to)\b", re.IGNORECASE),
    re.compile(r"\bgoing forward\b", re.IGNORECASE),
    re.compile(r"\bfrom now on\b", re.IGNORECASE),
]
# Phrases that signal a team or project norm rather than a personal preference.
_NORM_PATTERNS = [
    re.compile(r"\bwe (?:always|never|use|announce|name)\b", re.IGNORECASE),
    re.compile(r"\b(?:the )?convention is\b", re.IGNORECASE),
    re.compile(r"\bnaming convention\b", re.IGNORECASE),
    re.compile(r"\bformat\b.*\bis\b", re.IGNORECASE),
]
# Phrases that signal a correction of the agent.
_CORRECTION_PATTERNS = [
    re.compile(r"\b(?:actually|no,|that's wrong|not quite|instead)\b", re.IGNORECASE),
    re.compile(r"\bshould (?:have|be)\b", re.IGNORECASE),
]


@dataclass
class ExtractedCandidate:
    """A memory candidate with where it came from, before scoring."""

    candidate: MemoryCandidate
    source_kind: str  # explicit | correction | procedure | app_norm
    evidence_ref: str
    evidence_type: str = "trace"
    extra: dict[str, Any] = field(default_factory=dict)


def _matches_any(text: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(p.search(text) for p in patterns)


def extract_from_trajectory(run: TraceRun) -> list[ExtractedCandidate]:
    """Extract candidates from one agent trajectory.

    Looks at user turns for explicit statements and corrections, and at the run's
    own emitted memory candidates (which converters or an LLM may have attached).
    """
    out: list[ExtractedCandidate] = []

    # Candidates the trajectory explicitly emitted are trusted signals.
    for cand in run.all_memory_candidates():
        out.append(
            ExtractedCandidate(
                candidate=cand, source_kind="explicit", evidence_ref=run.trace_id,
            )
        )

    spans = run.spans
    for i, span in enumerate(spans):
        if span.kind != SpanKind.USER:
            continue
        text = (span.input or "").strip()
        if not text:
            continue

        is_correction = _matches_any(text, _CORRECTION_PATTERNS) and _has_prior_tool(spans, i)
        is_norm = _matches_any(text, _NORM_PATTERNS)
        is_pref = _matches_any(text, _PREFERENCE_PATTERNS)

        if is_correction:
            out.append(ExtractedCandidate(
                candidate=MemoryCandidate(
                    text=text, kind="procedural", namespace="user",
                    confidence_hint=0.6,
                ),
                source_kind="correction", evidence_ref=run.trace_id,
            ))
        elif is_norm:
            out.append(ExtractedCandidate(
                candidate=MemoryCandidate(
                    text=text, kind="semantic", namespace="team",
                    confidence_hint=0.55,
                ),
                source_kind="explicit", evidence_ref=run.trace_id,
            ))
        elif is_pref:
            out.append(ExtractedCandidate(
                candidate=MemoryCandidate(
                    text=text, kind="semantic", namespace="user",
                    confidence_hint=0.7,
                ),
                source_kind="explicit", evidence_ref=run.trace_id,
            ))

    return out


def _has_prior_tool(spans: list, index: int) -> bool:
    return any(s.kind == SpanKind.TOOL for s in spans[:index])


def extract_repeated_procedures(
    runs: list[TraceRun], *, min_occurrences: int = 2
) -> list[ExtractedCandidate]:
    """Detect tool sequences repeated across runs as procedural candidates.

    A workflow performed the same way several times is a strong candidate for a
    reusable procedure, which is the procedural memory the task description calls for.
    """
    sequences: dict[tuple[str, ...], list[str]] = {}
    for run in runs:
        tools = tuple(s.tool_name for s in run.spans if s.kind == SpanKind.TOOL and s.tool_name)
        if len(tools) >= 2:
            sequences.setdefault(tools, []).append(run.trace_id)

    out: list[ExtractedCandidate] = []
    for seq, trace_ids in sequences.items():
        if len(trace_ids) >= min_occurrences:
            out.append(ExtractedCandidate(
                candidate=MemoryCandidate(
                    text="Repeated workflow " + " then ".join(seq),
                    kind="procedural", namespace="team", confidence_hint=0.6,
                ),
                source_kind="procedure", evidence_ref=",".join(trace_ids),
                extra={"sequence": list(seq), "occurrences": len(trace_ids)},
            ))
    return out


def extract_from_app_state(events: EventStore) -> list[ExtractedCandidate]:
    """Extract durable conventions stated in current app state.

    Scans the latest messages and documents for norm and convention phrasing. This
    is the bootstrapping signal that lets the knowledge base be useful before many
    trajectories exist, the cold start path.
    """
    out: list[ExtractedCandidate] = []
    states = events.materialize()
    for (app, entity_type, entity_id), state in states.items():
        text = ""
        if entity_type == "message":
            text = state.payload.get("text", "")
        elif entity_type == "document":
            text = state.payload.get("markdown", "")
        if not text:
            continue
        for line in text.splitlines():
            line = line.strip()
            if len(line) < 8:
                continue
            if _matches_any(line, _NORM_PATTERNS):
                ns = "project" if entity_type == "document" else "team"
                out.append(ExtractedCandidate(
                    candidate=MemoryCandidate(
                        text=line, kind="semantic", namespace=ns, confidence_hint=0.5,
                    ),
                    source_kind="app_norm", evidence_ref=entity_id,
                    evidence_type="event",
                    extra={"app": app, "entity_type": entity_type},
                ))
    return out
