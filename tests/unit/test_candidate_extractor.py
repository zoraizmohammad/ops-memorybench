"""Tests for memory candidate extraction."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ombench.events.store import EventStore
from ombench.integrations.gdocs.sync import GDocsSync
from ombench.integrations.slack.sync import SlackSync
from ombench.memory.candidate_extractor import (
    extract_from_app_state,
    extract_from_trajectory,
    extract_repeated_procedures,
)
from ombench.storage import open_memory_store
from ombench.timeutil import UTC, FrozenClock
from ombench.traces.schema import AppRef, SpanKind, TraceRun, TraceSpan

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def t(minute: int) -> datetime:
    return datetime(2026, 5, 14, 17, minute, 0, tzinfo=UTC)


def test_extract_explicit_preference():
    run = TraceRun(agent="claude_code", started_at=t(0))
    run.add_span(TraceSpan(kind=SpanKind.USER, started_at=t(0),
                           input="I prefer afternoons and never Fridays"))
    cands = extract_from_trajectory(run)
    assert any(c.source_kind == "explicit" for c in cands)
    pref = next(c for c in cands if c.source_kind == "explicit")
    assert pref.candidate.namespace == "user"


def test_extract_correction_after_tool():
    run = TraceRun(agent="claude_code", started_at=t(0))
    run.add_span(TraceSpan(kind=SpanKind.TOOL, tool_name="slack.post", started_at=t(0)))
    run.add_span(TraceSpan(kind=SpanKind.USER, started_at=t(1),
                           input="Actually that should have gone to announcements"))
    cands = extract_from_trajectory(run)
    assert any(c.source_kind == "correction" for c in cands)


def test_correction_requires_prior_tool():
    run = TraceRun(agent="claude_code", started_at=t(0))
    run.add_span(TraceSpan(kind=SpanKind.USER, started_at=t(0),
                           input="Actually never mind"))
    cands = extract_from_trajectory(run)
    # No prior tool, so this is not treated as a correction.
    assert not any(c.source_kind == "correction" for c in cands)


def test_extract_norm():
    run = TraceRun(agent="claude_code", started_at=t(0))
    run.add_span(TraceSpan(kind=SpanKind.USER, started_at=t(0),
                           input="We always announce launches in the announcements channel"))
    cands = extract_from_trajectory(run)
    norm = next(c for c in cands if c.candidate.namespace == "team")
    assert norm.candidate.kind == "semantic"


def test_emitted_candidates_are_extracted():
    from ombench.traces.schema import MemoryCandidate

    run = TraceRun(agent="claude_code", started_at=t(0))
    run.add_span(TraceSpan(
        kind=SpanKind.TOOL, tool_name="gcal.update", started_at=t(0),
        app_refs=[AppRef(app="gcal", entity_type="event", entity_id="ev1")],
        memory_candidates=[MemoryCandidate(text="user is in Pacific time", kind="semantic")],
    ))
    cands = extract_from_trajectory(run)
    assert any("Pacific" in c.candidate.text for c in cands)


def test_repeated_procedures():
    runs = []
    for _ in range(3):
        r = TraceRun(agent="claude_code", started_at=t(0))
        r.add_span(TraceSpan(kind=SpanKind.TOOL, tool_name="gcal.get_event", started_at=t(0)))
        r.add_span(TraceSpan(kind=SpanKind.TOOL, tool_name="gcal.update_event", started_at=t(1)))
        runs.append(r)
    cands = extract_repeated_procedures(runs, min_occurrences=2)
    assert len(cands) == 1
    assert cands[0].source_kind == "procedure"
    assert cands[0].extra["occurrences"] == 3


def test_no_repeated_procedure_below_threshold():
    r = TraceRun(agent="claude_code", started_at=t(0))
    r.add_span(TraceSpan(kind=SpanKind.TOOL, tool_name="a", started_at=t(0)))
    r.add_span(TraceSpan(kind=SpanKind.TOOL, tool_name="b", started_at=t(1)))
    assert extract_repeated_procedures([r], min_occurrences=2) == []


@pytest.fixture
def app_state():
    s = open_memory_store()
    es = EventStore(s.backend, s.blobs)
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    SlackSync(es, clock=clock, fixtures_path=FIXTURES / "slack" / "workspace.json").run_sync()
    GDocsSync(es, clock=clock, fixtures_path=FIXTURES / "gdocs" / "docs.json").run_sync()
    yield es
    s.close()


def test_extract_from_app_state_finds_conventions(app_state):
    cands = extract_from_app_state(app_state)
    texts = [c.candidate.text for c in cands]
    # The Slack message stating the announcement format and the Docs naming
    # convention should both surface.
    assert any("announce" in tx.lower() or "format" in tx.lower() for tx in texts)
    assert any("naming convention" in tx.lower() or "named Customer" in tx for tx in texts)


def test_app_state_candidates_have_event_evidence(app_state):
    cands = extract_from_app_state(app_state)
    assert cands
    assert all(c.evidence_type == "event" for c in cands)
