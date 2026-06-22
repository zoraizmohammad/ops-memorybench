"""End to end backtest integration test.

Syncs fixtures, compiles the knowledge base, then runs the paired with vs without
memory backtest over the benchmark tasks and asserts that memory measurably improves
the rubric total. This is the proof the platform exists to produce.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ombench.eval.runner import BacktestRunner
from ombench.eval.tasks import load_tasks
from ombench.events.store import EventStore
from ombench.integrations.gcal.sync import GCalSync
from ombench.integrations.slack.sync import SlackSync
from ombench.llm.stub import StubLLM
from ombench.memory.compiler import KnowledgeCompiler
from ombench.storage import open_store
from ombench.timeutil import UTC, FrozenClock
from ombench.traces.converters import from_claude_code_session

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "fixtures"
BENCHMARKS = REPO / "benchmarks" / "tasks"


@pytest.fixture
def compiled_store(config):
    store = open_store(config)
    es = EventStore(store.backend, store.blobs)
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    SlackSync(es, clock=clock, fixtures_path=FIXTURES / "slack" / "workspace.json").run_sync()
    GCalSync(es, clock=clock, fixtures_path=FIXTURES / "gcal" / "calendar.json").run_sync()
    # Compile memory from the reschedule trajectory and from app state, so the
    # afternoon preference and the announcement convention are both available.
    run = from_claude_code_session(FIXTURES / "trajectories" / "claude_code_reschedule.jsonl")
    KnowledgeCompiler(store).compile(runs=[run], include_app_state=True, write_files=False)
    yield store
    store.close()


def test_backtest_memory_helps(compiled_store):
    tasks = load_tasks(BENCHMARKS)
    runner = BacktestRunner(compiled_store, llm=StubLLM())
    report = runner.run(tasks)

    assert len(report.results) == len(tasks)
    # Memory should help on at least one task and never hurt overall.
    assert report.win_rate() > 0
    assert sum(report.deltas()) > 0


def test_reschedule_task_improves_with_memory(compiled_store):
    tasks = [t for t in load_tasks(BENCHMARKS) if t.task_id == "01_reschedule_1on1"]
    runner = BacktestRunner(compiled_store, llm=StubLLM())
    result = runner.run_task(tasks[0])
    # Without memory the agent picks the noon default and fails the outcome; with
    # memory it picks the afternoon and succeeds.
    assert not result.without_memory.scores.success
    assert result.with_memory.scores.success
    assert result.total_delta > 0


def test_backtest_records_writes_and_tokens(compiled_store):
    tasks = [t for t in load_tasks(BENCHMARKS) if t.task_id == "01_reschedule_1on1"]
    result = BacktestRunner(compiled_store, llm=StubLLM()).run_task(tasks[0])
    assert result.with_memory.writes
    assert result.with_memory.input_tokens > 0


def test_announce_task_routes_with_memory(compiled_store):
    tasks = [t for t in load_tasks(BENCHMARKS) if t.task_id == "02_announce_launch"]
    result = BacktestRunner(compiled_store, llm=StubLLM()).run_task(tasks[0])
    # With memory the agent should reach the announcements channel.
    with_writes = result.with_memory.writes
    assert any(w["payload"].get("channel") in ("announcements", "C_ANNOUNCE") for w in with_writes)
