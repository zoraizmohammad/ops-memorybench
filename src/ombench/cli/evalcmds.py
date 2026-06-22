"""``omb eval`` command group and the top level ``omb demo``.

Operator commands for Tasks 4 and 6: run the paired backtest over the benchmark and
print the results table, mine candidate tasks from captured trajectories, and run the
full end to end demo that syncs fixtures, seeds memory, and backtests in one command.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console

from ..config import load_config
from ..eval.miner import mine_candidates
from ..eval.reports import summarize, to_markdown
from ..eval.runner import BacktestRunner
from ..eval.seed import load_memory_seed
from ..eval.tasks import load_tasks
from ..events.store import EventStore
from ..integrations.gcal.sync import GCalSync
from ..integrations.gdocs.sync import GDocsSync
from ..integrations.slack.sync import SlackSync
from ..llm import build_llm
from ..storage import open_store
from ..timeutil import UTC, FrozenClock
from ..traces.ingest import TrajectoryIngestor

app = typer.Typer(help="Run the backtest and mine tasks.", no_args_is_help=True)
console = Console()


@app.command("run")
def run_cmd(
    tasks_dir: str = typer.Option("benchmarks/tasks", help="Directory of task specs."),
) -> None:
    """Run the paired with vs without memory backtest and print the results."""
    config = load_config()
    store = open_store(config)
    try:
        tasks = load_tasks(config.repo_root / tasks_dir)
        runner = BacktestRunner(store, llm=build_llm(config))
        report = runner.run(tasks)
        console.print(to_markdown(report))
    finally:
        store.close()


@app.command("mine")
def mine_cmd() -> None:
    """Mine candidate benchmark tasks from captured trajectories."""
    config = load_config()
    store = open_store(config)
    try:
        ingestor = TrajectoryIngestor(store)
        runs = [r for r in (ingestor.load(row["trace_id"]) for row in ingestor.list_runs()) if r]
        candidates = mine_candidates(runs)
        if not candidates:
            console.print("no candidate tasks mined (need more trajectories)")
            return
        for c in candidates:
            console.print(f"[bold]{c.kind}[/bold] {c.summary}")
            console.print(f"  evidence {c.evidence_traces}")
            console.print(f"  rationale {c.rationale}")
    finally:
        store.close()


def _seed_demo_store(config):
    """Sync fixtures and load the curated memory seed for the demo. Returns a Store."""
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
    return store


def demo() -> None:
    """Run the full end to end demo and print the backtest results.

    Syncs the bundled fixtures, loads the curated memory seed, and runs the paired
    backtest over the fifteen benchmark tasks. With no credentials this is fully
    deterministic and keyless.
    """
    config = load_config()
    console.print("[bold]ombench demo[/bold] syncing fixtures and seeding memory")
    store = _seed_demo_store(config)
    try:
        tasks = load_tasks(config.benchmarks_dir / "tasks")
        console.print(f"running paired backtest over {len(tasks)} tasks")
        report = BacktestRunner(store, llm=build_llm(config)).run(tasks)
        console.print(to_markdown(report))
        s = summarize(report)
        console.print(
            f"\n[bold green]Memory raised the mean outcome score from "
            f"{s['mean_outcome_without']} to {s['mean_outcome_with']} and success from "
            f"{s['success_without']} to {s['success_with']} (win rate {s['win_rate']}, "
            f"Wilcoxon p {s['wilcoxon_p']}).[/bold green]"
        )
    finally:
        store.close()
