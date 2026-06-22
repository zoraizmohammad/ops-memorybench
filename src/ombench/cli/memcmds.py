"""``omb memory`` command group.

Operator commands for Task 3: compile the knowledge base from captured trajectories
and app state, bootstrap from existing data, inspect compiled items and provenance,
and run a retrieval query to see what the agent would be given.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ..config import load_config
from ..memory.bootstrap import ColdStartBootstrapper
from ..memory.compiler import KnowledgeCompiler
from ..memory.retriever import MemoryRetriever
from ..memory.store import MemoryStore
from ..storage import open_store
from ..traces.ingest import TrajectoryIngestor

app = typer.Typer(help="Compile and query the knowledge base.", no_args_is_help=True)
console = Console()


@app.command("compile")
def compile_cmd(
    app_state: bool = typer.Option(True, help="Include current app state as a source."),
) -> None:
    """Compile the knowledge base from all captured trajectories and app state."""
    config = load_config()
    store = open_store(config)
    try:
        ingestor = TrajectoryIngestor(store)
        loaded = [ingestor.load(r["trace_id"]) for r in ingestor.list_runs()]
        runs = [r for r in loaded if r is not None]
        compiler = KnowledgeCompiler(store)
        result = compiler.compile(runs=runs, include_app_state=app_state, kb_root=config.kb_dir)
        console.print(
            f"compiled from {len(runs)} runs candidates {result.candidates} "
            f"promoted {result.promoted} contradictions resolved "
            f"{result.contradictions_resolved}"
        )
        for f in result.files_written:
            console.print(f"  wrote {f}")
    finally:
        store.close()


@app.command("bootstrap")
def bootstrap_cmd() -> None:
    """Cold start the knowledge base from existing integration data."""
    config = load_config()
    store = open_store(config)
    try:
        result = ColdStartBootstrapper(store).bootstrap(kb_root=config.kb_dir)
        console.print(
            f"bootstrapped structured facts {result.structured_facts} "
            f"total promoted {result.total_promoted}"
        )
    finally:
        store.close()


@app.command("list")
def list_cmd(active_only: bool = typer.Option(True, help="Only active items.")) -> None:
    """List compiled memory items."""
    config = load_config()
    store = open_store(config)
    try:
        items = MemoryStore(store).all_items(active_only=active_only)
        table = Table(title="memory items")
        table.add_column("memory_id")
        table.add_column("type")
        table.add_column("namespace")
        table.add_column("subject")
        table.add_column("conf")
        table.add_column("claim")
        for it in items:
            table.add_row(
                it.memory_id, it.type.value, it.namespace.value, it.subject or "",
                f"{it.confidence:.2f}", it.claim[:60],
            )
        console.print(table)
    finally:
        store.close()


@app.command("show")
def show_cmd(memory_id: str = typer.Argument(...)) -> None:
    """Show one memory item and its provenance."""
    config = load_config()
    store = open_store(config)
    try:
        item = MemoryStore(store).get(memory_id)
        if item is None:
            console.print(f"[red]no memory {memory_id}[/red]")
            raise typer.Exit(code=1)
        console.print(f"[bold]{item.claim}[/bold]")
        console.print(f"type {item.type.value} namespace {item.namespace.value} "
                      f"confidence {item.confidence:.2f} active {item.active}")
        console.print(f"ttl {item.ttl_policy.value} acl {item.acl}")
        for ev in item.evidence:
            console.print(f"  evidence {ev.kind} {ev.ref} {ev.note or ''}")
    finally:
        store.close()


@app.command("retrieve")
def retrieve_cmd(
    query: str = typer.Argument(...),
    top_k: int = typer.Option(5, help="Number of items to return."),
) -> None:
    """Run a retrieval query and show the memory bundle the agent would receive."""
    config = load_config()
    store = open_store(config)
    try:
        retriever = MemoryRetriever(MemoryStore(store))
        bundle = retriever.retrieve(query, top_k=top_k)
        console.print(f"[bold]query[/bold] {query}")
        console.print(f"tokens about {bundle.token_estimate}")
        for r in bundle.items:
            via = "graph" if r.via_graph else "search"
            console.print(f"  [{r.item.type.value}] {r.item.claim}  (score {r.score:.3f} via {via})")
    finally:
        store.close()
