"""``omb viz`` command group.

Exposes the visualization and trust surfaces: render a provenance graph, walk an
entity through time, list the approval queue, and write an HTML backtest dashboard.
These are the demo facing windows onto the platform.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console

from ..config import load_config
from ..eval.runner import BacktestRunner
from ..eval.seed import load_memory_seed
from ..eval.tasks import load_tasks
from ..events.store import EventStore
from ..integrations.gcal.sync import GCalSync
from ..integrations.gdocs.sync import GDocsSync
from ..integrations.slack.sync import SlackSync
from ..llm import build_llm
from ..memory.store import MemoryStore
from ..storage import open_store
from ..timeutil import UTC, FrozenClock
from ..viz.provenance import to_dot
from ..viz.report_html import render_html
from ..viz.timetravel import entity_timeline, render_timeline_text

app = typer.Typer(help="Visualization and trust surfaces.", no_args_is_help=True)
console = Console()


@app.command("provenance")
def provenance_cmd(
    out: str = typer.Option(None, help="Write DOT to this path instead of stdout."),
) -> None:
    """Render the memory provenance graph as Graphviz DOT."""
    config = load_config()
    store = open_store(config)
    try:
        dot = to_dot(MemoryStore(store))
        if out:
            Path(out).write_text(dot, encoding="utf-8")
            console.print(f"wrote provenance graph to {out}")
        else:
            console.print(dot)
    finally:
        store.close()


@app.command("timetravel")
def timetravel_cmd(
    app_name: str = typer.Argument(...),
    entity_type: str = typer.Argument(...),
    entity_id: str = typer.Argument(...),
) -> None:
    """Walk an entity through its versions over time."""
    config = load_config()
    store = open_store(config)
    try:
        es = EventStore(store.backend, store.blobs)
        frames = entity_timeline(es, app_name, entity_type, entity_id)
        if not frames:
            console.print("no history for that entity")
            return
        console.print(render_timeline_text(frames))
    finally:
        store.close()


@app.command("dashboard")
def dashboard_cmd(
    out: str = typer.Option("backtest.html", help="Output HTML path."),
) -> None:
    """Run the demo backtest and write a self contained HTML dashboard."""
    config = load_config()
    store = open_store(config)
    try:
        es = EventStore(store.backend, store.blobs)
        clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
        fx = config.fixtures_dir
        SlackSync(es, clock=clock, fixtures_path=fx / "slack" / "workspace.json").run_sync()
        GCalSync(es, clock=clock, fixtures_path=fx / "gcal" / "calendar.json").run_sync()
        GDocsSync(es, clock=clock, fixtures_path=fx / "gdocs" / "docs.json").run_sync()
        seed = config.benchmarks_dir / "memory_seed.yaml"
        if Path(seed).exists():
            load_memory_seed(store, seed)
        tasks = load_tasks(config.benchmarks_dir / "tasks")
        report = BacktestRunner(store, llm=build_llm(config)).run(tasks)
        Path(out).write_text(render_html(report), encoding="utf-8")
        console.print(f"wrote backtest dashboard to {out}")
    finally:
        store.close()
