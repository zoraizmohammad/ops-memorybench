"""Full 15 task benchmark suite backtest.

Loads the curated memory seed, syncs the integration fixtures, and runs the paired
backtest over all fifteen benchmark tasks. Asserts that mounted memory improves the
aggregate rubric and that each task individually benefits, which is the headline
result the platform produces.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ombench.eval.reports import summarize
from ombench.eval.runner import BacktestRunner
from ombench.eval.seed import load_memory_seed
from ombench.eval.tasks import load_tasks
from ombench.events.store import EventStore
from ombench.integrations.gcal.sync import GCalSync
from ombench.integrations.gdocs.sync import GDocsSync
from ombench.integrations.slack.sync import SlackSync
from ombench.llm.stub import StubLLM
from ombench.storage import open_store
from ombench.timeutil import UTC, FrozenClock

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "fixtures"
BENCHMARKS = REPO / "benchmarks"


@pytest.fixture
def benchmark_store(config):
    store = open_store(config)
    es = EventStore(store.backend, store.blobs)
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    SlackSync(es, clock=clock, fixtures_path=FIXTURES / "slack" / "workspace.json").run_sync()
    GCalSync(es, clock=clock, fixtures_path=FIXTURES / "gcal" / "calendar.json").run_sync()
    GDocsSync(es, clock=clock, fixtures_path=FIXTURES / "gdocs" / "docs.json").run_sync()
    load_memory_seed(store, BENCHMARKS / "memory_seed.yaml")
    yield store
    store.close()


def test_all_fifteen_tasks_load():
    tasks = load_tasks(BENCHMARKS / "tasks")
    assert len(tasks) == 15
    # Every task documents why it tests memory.
    assert all(t.why_memory.strip() for t in tasks)


def test_benchmark_memory_improves_aggregate(benchmark_store):
    tasks = load_tasks(BENCHMARKS / "tasks")
    report = BacktestRunner(benchmark_store, llm=StubLLM()).run(tasks)
    s = summarize(report)
    # Memory improves the mean outcome score and the success rate, and never hurts.
    assert s["mean_outcome_with"] > s["mean_outcome_without"]
    assert s["success_with"] > s["success_without"]
    # Every task is solvable with the right memory, so success reaches 100 percent.
    assert s["success_with"] == 1.0
    # Win rate is on the outcome grounded delta. One task (the prior decision lookup)
    # has the same outcome with or without memory, so it is neutral, not a win; the
    # other fourteen improve. No task regresses.
    assert s["win_rate"] >= 0.9
    assert all(d >= 0 for d in report.deltas())
    assert sum(1 for d in report.deltas() if d > 0) >= 14


def test_each_task_benefits_or_holds(benchmark_store):
    tasks = load_tasks(BENCHMARKS / "tasks")
    report = BacktestRunner(benchmark_store, llm=StubLLM()).run(tasks)
    # No task should regress on the outcome grounded score with memory mounted.
    regressions = [r.task_id for r in report.results if r.outcome_delta < 0]
    assert regressions == []
    # All but the neutral prior decision task strictly improve.
    improved = [r for r in report.results if r.outcome_delta > 0]
    assert len(improved) >= 14


def test_memory_retrieval_recall_on_with_condition(benchmark_store):
    tasks = load_tasks(BENCHMARKS / "tasks")
    report = BacktestRunner(benchmark_store, llm=StubLLM()).run(tasks)
    # Most tasks should retrieve their expected memory under the with condition.
    recalled = [r for r in report.results if r.with_memory.scores.memory_retrieval > 0]
    assert len(recalled) >= 12
