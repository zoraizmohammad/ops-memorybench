"""Procedure synthesizer.

Converts repeated trajectories into an executable playbook. When the same tool
sequence recurs across runs, that workflow is worth capturing as a procedure: an
ordered list of steps with the tools and the argument shape, plus the preconditions
observed. The synthesized procedure is a procedural memory item the agent can read to
perform the workflow consistently.

This complements the candidate extractor's procedural detection by producing a
structured, step by step playbook rather than a one line claim.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..traces.schema import SpanKind, TraceRun


@dataclass
class ProcedureStep:
    tool: str
    arg_keys: list[str] = field(default_factory=list)


@dataclass
class Procedure:
    name: str
    steps: list[ProcedureStep]
    occurrences: int
    trace_ids: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [f"# Procedure {self.name}", "", f"Observed {self.occurrences} times.", "", "## Steps", ""]
        for i, step in enumerate(self.steps, 1):
            args = ", ".join(step.arg_keys) if step.arg_keys else "no arguments"
            lines.append(f"{i}. {step.tool} ({args})")
        return "\n".join(lines)

    def to_claim(self) -> str:
        return "Workflow " + " then ".join(s.tool for s in self.steps)


def _tool_sequence(run: TraceRun) -> tuple[str, ...]:
    return tuple(s.tool_name for s in run.spans if s.kind == SpanKind.TOOL and s.tool_name)


def _arg_keys(run: TraceRun, tool: str) -> list[str]:
    for s in run.spans:
        if s.kind == SpanKind.TOOL and s.tool_name == tool and s.tool_args:
            return sorted(s.tool_args.keys())
    return []


def synthesize(runs: list[TraceRun], *, min_occurrences: int = 2) -> list[Procedure]:
    """Synthesize procedures from tool sequences repeated across runs."""
    sequences: dict[tuple[str, ...], list[str]] = {}
    for run in runs:
        seq = _tool_sequence(run)
        if len(seq) >= 2:
            sequences.setdefault(seq, []).append(run.trace_id)

    procedures: list[Procedure] = []
    for seq, trace_ids in sequences.items():
        if len(trace_ids) < min_occurrences:
            continue
        # Use the first run that produced this sequence to read argument shapes.
        sample = next(r for r in runs if _tool_sequence(r) == seq)
        steps = [ProcedureStep(tool=t, arg_keys=_arg_keys(sample, t)) for t in seq]
        name = _name_for(seq)
        procedures.append(
            Procedure(name=name, steps=steps, occurrences=len(trace_ids), trace_ids=trace_ids)
        )
    return procedures


def _name_for(seq: tuple[str, ...]) -> str:
    # Name the procedure after the most distinctive verb in its tools.
    verbs = Counter()
    for tool in seq:
        for part in tool.replace(".", "_").split("_"):
            if part not in ("get", "list", "slack", "gcal", "gdocs"):
                verbs[part] += 1
    top = verbs.most_common(1)
    return (top[0][0] if top else "workflow") + "_procedure"
