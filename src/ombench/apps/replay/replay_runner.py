"""Replay runner entrypoint.

A thin programmatic entrypoint that wires storage, seeds the curated memory, and runs
the paired backtest, returning the structured report. The CLI ``omb demo`` is the
operator facing form of this; this module is the importable form for embedding the
backtest in a notebook, a CI gate, or another service.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ...config import Config, load_config
from ...eval.runner import BacktestReport, BacktestRunner
from ...eval.seed import load_memory_seed
from ...eval.tasks import load_tasks
from ...events.store import EventStore
from ...integrations.gcal.sync import GCalSync
from ...integrations.gdocs.sync import GDocsSync
from ...integrations.slack.sync import SlackSync
from ...llm import build_llm
from ...storage import open_store
from ...timeutil import UTC, FrozenClock


def run_backtest(config: Config | None = None) -> BacktestReport:
    """Seed storage from fixtures and the curated memory, then run the backtest."""
    config = config or load_config()
    store = open_store(config)
    es = EventStore(store.backend, store.blobs)
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    fx = config.fixtures_dir
    SlackSync(es, clock=clock, fixtures_path=fx / "slack" / "workspace.json").run_sync()
    GCalSync(es, clock=clock, fixtures_path=fx / "gcal" / "calendar.json").run_sync()
    GDocsSync(es, clock=clock, fixtures_path=fx / "gdocs" / "docs.json").run_sync()
    seed = config.benchmarks_dir / "memory_seed.yaml"
    if Path(seed).exists():
        load_memory_seed(store, seed)
    try:
        tasks = load_tasks(config.benchmarks_dir / "tasks")
        return BacktestRunner(store, llm=build_llm(config)).run(tasks)
    finally:
        store.close()
