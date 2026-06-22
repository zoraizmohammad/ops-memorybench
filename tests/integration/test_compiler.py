"""Integration tests for the knowledge base compiler."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ombench.events.store import EventStore
from ombench.integrations.gdocs.sync import GDocsSync
from ombench.integrations.slack.sync import SlackSync
from ombench.memory.compiler import KnowledgeCompiler
from ombench.memory.kb import KnowledgeBase
from ombench.storage import open_store
from ombench.timeutil import UTC, FrozenClock
from ombench.traces.converters import from_claude_code_session
from ombench.traces.schema import SpanKind, TraceRun, TraceSpan

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def t(minute: int) -> datetime:
    return datetime(2026, 5, 14, 17, minute, 0, tzinfo=UTC)


@pytest.fixture
def store(config):
    s = open_store(config)
    es = EventStore(s.backend, s.blobs)
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    SlackSync(es, clock=clock, fixtures_path=FIXTURES / "slack" / "workspace.json").run_sync()
    GDocsSync(es, clock=clock, fixtures_path=FIXTURES / "gdocs" / "docs.json").run_sync()
    yield s
    s.close()


def test_compile_from_trajectory_and_app_state(store, config):
    run = from_claude_code_session(FIXTURES / "trajectories" / "claude_code_reschedule.jsonl")
    compiler = KnowledgeCompiler(store)
    result = compiler.compile(runs=[run], kb_root=config.kb_dir)
    assert result.candidates > 0
    assert result.promoted > 0
    assert result.files_written

    # The knowledge base filesystem now exists and is readable.
    kb = KnowledgeBase(config.kb_dir)
    text = kb.mounted_text()
    # The user preference for afternoons should be compiled in.
    assert "afternoon" in text.lower()


def test_compiled_items_have_provenance(store, config):
    run = from_claude_code_session(FIXTURES / "trajectories" / "claude_code_reschedule.jsonl")
    compiler = KnowledgeCompiler(store)
    compiler.compile(runs=[run], kb_root=config.kb_dir)
    kb = KnowledgeBase(config.kb_dir)
    items = compiler.memory.all_items(active_only=True)
    assert items
    prov = kb.read_provenance(items[0].memory_id)
    assert prov is not None
    assert prov["claim"]


def test_recompile_is_deterministic(store, config):
    run = from_claude_code_session(FIXTURES / "trajectories" / "claude_code_reschedule.jsonl")
    c1 = KnowledgeCompiler(store)
    r1 = c1.compile(runs=[run], kb_root=config.kb_dir, write_files=False)
    # Re running adds nothing new because ids are content derived.
    c2 = KnowledgeCompiler(store)
    r2 = c2.compile(runs=[run], kb_root=config.kb_dir, write_files=False)
    assert r2.promoted == 0 or len(c2.memory.all_items()) == len(c1.memory.all_items())
    assert r1.promoted >= 1


def test_contradiction_resolved_in_compile(store, config):
    # Two runs with opposing preferences; the resolver keeps one active.
    r1 = TraceRun(agent="claude_code", started_at=t(0))
    r1.add_span(TraceSpan(kind=SpanKind.USER, started_at=t(0),
                          input="I prefer morning meetings"))
    r2 = TraceRun(agent="claude_code", started_at=t(5))
    r2.add_span(TraceSpan(kind=SpanKind.USER, started_at=t(5),
                          input="I prefer not morning meetings going forward"))
    compiler = KnowledgeCompiler(store)
    result = compiler.compile(runs=[r1, r2], include_app_state=False, kb_root=config.kb_dir)
    # At least the two preferences were promoted and a contradiction resolved.
    assert result.promoted >= 2
    active = compiler.memory.all_items(active_only=True)
    morning_items = [i for i in active if "morning" in i.claim.lower()]
    # Only one polarity stays active.
    assert len(morning_items) == 1


def test_app_state_only_cold_start(store, config):
    # With no trajectories, the compiler still bootstraps from app state.
    compiler = KnowledgeCompiler(store)
    result = compiler.compile(runs=[], include_app_state=True, kb_root=config.kb_dir)
    assert result.promoted > 0
    kb = KnowledgeBase(config.kb_dir)
    text = kb.mounted_text().lower()
    assert "announce" in text or "convention" in text
