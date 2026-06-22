"""``omb trace`` command group.

Operator commands for trajectory capture: run the hook entrypoint, ingest a
transcript file, list captured runs, and show one trajectory. The hook command is
what the bundled Claude Code plugin invokes; the others are for inspection and for
importing sessions captured elsewhere.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ..config import load_config
from ..storage import open_store
from ..traces.converters import from_claude_code_session, from_codex_session
from ..traces.ingest import TrajectoryIngestor
from ..traces.schema import SpanKind

app = typer.Typer(help="Capture and inspect agent trajectories.", no_args_is_help=True)
console = Console()


@app.command()
def hook() -> None:
    """Run the capture hook, reading a Claude Code hook payload from stdin.

    This is the entrypoint the bundled plugin invokes. It is non blocking and
    always exits 0.
    """
    from ..traces.hook import main as hook_main

    raise typer.Exit(code=hook_main())


@app.command("ingest")
def ingest_cmd(
    path: Path = typer.Argument(..., help="Path to a transcript file."),
    agent: str = typer.Option("auto", help="auto | claude_code | codex"),
    group_id: str = typer.Option(None, help="Optional session group id."),
) -> None:
    """Ingest a transcript file into the history substrate."""
    config = load_config()
    store = open_store(config)
    try:
        if agent == "codex" or (agent == "auto" and path.suffix == ".json"):
            run = from_codex_session(path, group_id=group_id)
        else:
            run = from_claude_code_session(path, group_id=group_id)
        trace_id = TrajectoryIngestor(store).ingest(run)
        console.print(f"ingested {trace_id} with {len(run.spans)} spans")
    finally:
        store.close()


@app.command("list")
def list_cmd(agent: str = typer.Option(None, help="Filter by agent.")) -> None:
    """List captured trajectory runs."""
    config = load_config()
    store = open_store(config)
    try:
        runs = TrajectoryIngestor(store).list_runs(agent=agent)
        table = Table(title="captured trajectories")
        table.add_column("trace_id")
        table.add_column("agent")
        table.add_column("workflow")
        table.add_column("started")
        for r in runs:
            table.add_row(
                r["trace_id"], r["agent"] or "", r["workflow_name"] or "",
                r["started_at"] or "",
            )
        console.print(table)
    finally:
        store.close()


@app.command("show")
def show_cmd(trace_id: str = typer.Argument(...)) -> None:
    """Show one trajectory as a span tree summary."""
    config = load_config()
    store = open_store(config)
    try:
        run = TrajectoryIngestor(store).load(trace_id)
        if run is None:
            console.print(f"[red]no trajectory {trace_id}[/red]")
            raise typer.Exit(code=1)
        console.print(f"[bold]{run.trace_id}[/bold] agent={run.agent} spans={len(run.spans)}")
        for span in run.spans:
            marker = {
                SpanKind.USER: "user",
                SpanKind.LLM: "llm",
                SpanKind.TOOL: "tool",
                SpanKind.AGENT: "agent",
            }.get(span.kind, span.kind.value.lower())
            extra = f" {span.tool_name}" if span.tool_name else ""
            console.print(f"  [{marker}]{extra} {span.name or ''}")
        refs = run.all_app_refs()
        if refs:
            console.print("[dim]app refs:[/dim] " + json.dumps([r.model_dump() for r in refs]))
    finally:
        store.close()
