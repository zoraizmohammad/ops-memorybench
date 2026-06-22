"""Tests for benchmark task mining."""

from __future__ import annotations

from datetime import datetime

from ombench.eval.miner import mine_candidates
from ombench.timeutil import UTC
from ombench.traces.schema import SpanKind, TraceRun, TraceSpan


def t(minute):
    return datetime(2026, 5, 14, 17, minute, 0, tzinfo=UTC)


def _reschedule_run(i):
    r = TraceRun(agent="claude_code", started_at=t(0), task_ref=f"r{i}")
    r.add_span(TraceSpan(kind=SpanKind.TOOL, tool_name="gcal.get_event", started_at=t(0)))
    r.add_span(TraceSpan(kind=SpanKind.TOOL, tool_name="gcal.update_event", started_at=t(1)))
    return r


def test_mine_repeated_requests():
    runs = [_reschedule_run(i) for i in range(3)]
    candidates = mine_candidates(runs, min_repeats=2)
    repeated = [c for c in candidates if c.kind == "repeated_request"]
    assert repeated
    assert repeated[0].occurrences == 3


def test_mine_durable_statement():
    r = TraceRun(agent="claude_code", started_at=t(0))
    r.add_span(TraceSpan(kind=SpanKind.USER, started_at=t(0),
                         input="I prefer afternoons and never Fridays"))
    candidates = mine_candidates([r])
    durable = [c for c in candidates if c.kind == "durable_statement"]
    assert durable
    assert "afternoon" in durable[0].suggested_memory.lower()


def test_mine_repeated_corrections():
    runs = []
    for _ in range(2):
        r = TraceRun(agent="claude_code", started_at=t(0))
        r.add_span(TraceSpan(kind=SpanKind.TOOL, tool_name="slack.post", started_at=t(0)))
        r.add_span(TraceSpan(kind=SpanKind.USER, started_at=t(1),
                             input="Actually that should have gone to announcements channel"))
        runs.append(r)
    candidates = mine_candidates(runs, min_repeats=2)
    corrections = [c for c in candidates if c.kind == "correction"]
    assert corrections
    assert corrections[0].occurrences >= 2


def test_candidates_carry_evidence():
    runs = [_reschedule_run(i) for i in range(2)]
    candidates = mine_candidates(runs, min_repeats=2)
    assert all(c.evidence_traces for c in candidates)
    assert all(c.rationale for c in candidates)


def test_no_candidates_below_threshold():
    candidates = mine_candidates([_reschedule_run(0)], min_repeats=2)
    # A single run yields no repeated request candidate.
    assert not [c for c in candidates if c.kind == "repeated_request"]
