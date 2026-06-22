"""Benchmark task mining from trajectories.

A good memory task is one where the answer depends on durable context not reliably
inferable from the current app state alone, and where the expected effect of memory
can be judged with explicit evidence. This miner surfaces candidate tasks from real
trajectories by looking for the signals that mark such tasks:

- **repeated corrections**: the user corrected the agent on the same theme more than
  once, which means there is a durable lesson the agent kept missing
- **repeated requests**: the same kind of request recurs, so the workflow is worth
  a procedure
- **explicit durable statements**: the user stated a preference, norm, or convention

Each candidate carries the trajectory evidence and a suggested rationale, so a human
curator can promote it into a :class:`TaskSpec`. The miner deliberately does not
auto generate full specs: the prompt asks for curation judgement, and the rationale
plus evidence is what makes that judgement systematic.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..memory.candidate_extractor import extract_from_trajectory
from ..traces.schema import SpanKind, TraceRun


@dataclass
class TaskCandidate:
    """A mined candidate benchmark task awaiting human curation."""

    kind: str  # correction | repeated_request | durable_statement
    summary: str
    evidence_traces: list[str] = field(default_factory=list)
    suggested_memory: str = ""
    rationale: str = ""
    occurrences: int = 1


def _task_signature(run: TraceRun) -> str:
    """A coarse signature of what a run was trying to do, from its tool sequence."""
    tools = [s.tool_name for s in run.spans if s.kind == SpanKind.TOOL and s.tool_name]
    return ">".join(tools) if tools else "no_tools"


def mine_candidates(runs: list[TraceRun], *, min_repeats: int = 2) -> list[TaskCandidate]:
    """Mine candidate benchmark tasks from a set of trajectories."""
    candidates: list[TaskCandidate] = []

    # Repeated requests: the same tool signature recurring across runs.
    signatures: dict[str, list[str]] = {}
    for run in runs:
        sig = _task_signature(run)
        if sig != "no_tools":
            signatures.setdefault(sig, []).append(run.trace_id)
    for sig, traces in signatures.items():
        if len(traces) >= min_repeats:
            candidates.append(TaskCandidate(
                kind="repeated_request",
                summary=f"Recurring workflow {sig}",
                evidence_traces=traces,
                rationale=(
                    "This workflow recurs, so a procedure compiled from it should let "
                    "the agent perform it consistently. A good memory task replays one "
                    "instance and checks the procedure is followed."
                ),
                occurrences=len(traces),
            ))

    # Repeated corrections: correction candidates recurring across runs by theme.
    correction_themes: Counter[str] = Counter()
    correction_traces: dict[str, list[str]] = {}
    durable_statements: list[TaskCandidate] = []
    for run in runs:
        for cand in extract_from_trajectory(run):
            theme = _theme(cand.candidate.text)
            if cand.source_kind == "correction":
                correction_themes[theme] += 1
                correction_traces.setdefault(theme, []).append(run.trace_id)
            elif cand.source_kind == "explicit":
                durable_statements.append(TaskCandidate(
                    kind="durable_statement",
                    summary=cand.candidate.text[:80],
                    evidence_traces=[run.trace_id],
                    suggested_memory=cand.candidate.text,
                    rationale=(
                        "The user stated a durable preference or norm. A good memory "
                        "task is one whose correct answer depends on this statement but "
                        "where the current app snapshot does not reveal it."
                    ),
                ))

    for theme, count in correction_themes.items():
        if count >= min_repeats:
            candidates.append(TaskCandidate(
                kind="correction",
                summary=f"Repeated correction about {theme}",
                evidence_traces=correction_traces[theme],
                rationale=(
                    "The agent was corrected on the same theme more than once, which "
                    "means there is a durable lesson it kept missing. This is among the "
                    "strongest signals for a memory task."
                ),
                occurrences=count,
            ))

    # Deduplicate durable statements by summary, keeping the first.
    seen: set[str] = set()
    for c in durable_statements:
        if c.summary not in seen:
            seen.add(c.summary)
            candidates.append(c)

    return candidates


_STOP = {"the", "a", "an", "to", "i", "my", "in", "on", "and", "is", "of", "please", "that"}


def _theme(text: str) -> str:
    """A coarse theme key for grouping corrections, the salient content words."""
    import re

    words = [w for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOP and len(w) > 3]
    return " ".join(sorted(set(words))[:3]) or "general"
