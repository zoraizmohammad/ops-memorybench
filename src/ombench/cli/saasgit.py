"""``omb saasgit`` command group.

The SaaS Git CLI makes the platform's core abstraction tangible: history as
something you can log, show, diff, and check out, just like git, but for SaaS state
reconstructed from the bitemporal event log. This is the extension that communicates
the whole idea in one command.

- ``log`` lists the history of an entity, its versions over time
- ``show`` reconstructs an entity as of a point in time
- ``diff`` compares state between two points in time
- ``checkout`` materializes the full app state as of a time into a snapshot
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ..config import load_config
from ..events.queries import entity_history, list_entities
from ..events.store import EventStore
from ..ids import canonical_json
from ..snapshots import SnapshotMaterializer, diff_snapshots
from ..storage import open_store
from ..timeutil import from_iso

app = typer.Typer(help="Git for SaaS state. log show diff checkout.", no_args_is_help=True)
console = Console()


@app.command("log")
def log_cmd(
    app_name: str = typer.Argument(..., help="App, for example gcal."),
    entity_type: str = typer.Argument(...),
    entity_id: str = typer.Argument(...),
) -> None:
    """Show the version history of one entity, oldest first."""
    config = load_config()
    store = open_store(config)
    try:
        es = EventStore(store.backend, store.blobs)
        history = entity_history(es, app_name, entity_type, entity_id)
        if not history:
            console.print("no history for that entity")
            return
        table = Table(title=f"history of {app_name}/{entity_type}/{entity_id}")
        table.add_column("valid_at")
        table.add_column("op")
        table.add_column("summary")
        for h in history:
            summary = canonical_json(h.payload)[:60]
            table.add_row(h.valid_at.isoformat(), h.op, summary)
        console.print(table)
    finally:
        store.close()


@app.command("show")
def show_cmd(
    app_name: str = typer.Argument(...),
    entity_type: str = typer.Argument(...),
    entity_id: str = typer.Argument(...),
    at: str = typer.Option(None, help="Valid time ISO 8601, defaults to latest."),
) -> None:
    """Reconstruct an entity as of a point in time."""
    config = load_config()
    store = open_store(config)
    try:
        es = EventStore(store.backend, store.blobs)
        valid = from_iso(at) if at else None
        state = es.materialize_entity(app_name, entity_type, entity_id, as_of_valid=valid)
        if state is None:
            console.print("entity not present at that time")
            return
        console.print(canonical_json(state.payload))
        if state.edges:
            edges = {k: sorted(v) for k, v in state.edges.items()}
            console.print(f"[dim]edges {edges}[/dim]")
    finally:
        store.close()


@app.command("diff")
def diff_cmd(
    before: str = typer.Argument(..., help="Before valid time ISO 8601."),
    after: str = typer.Argument(..., help="After valid time ISO 8601."),
    app_name: str = typer.Option(None, help="Limit to one app."),
) -> None:
    """Diff app state between two points in time."""
    config = load_config()
    store = open_store(config)
    try:
        mat = SnapshotMaterializer(store)
        b = mat.materialize(app=app_name, as_of_valid=from_iso(before), as_of_ingest=from_iso(after), persist=False)
        a = mat.materialize(app=app_name, as_of_valid=from_iso(after), as_of_ingest=from_iso(after), persist=False)
        d = diff_snapshots(b, a)
        console.print(d.summary())
        for key in d.added:
            console.print(f"[green]+ {key}[/green]")
        for key in d.removed:
            console.print(f"[red]- {key}[/red]")
        for key in d.changed:
            console.print(f"[yellow]~ {key}[/yellow]")
    finally:
        store.close()


@app.command("checkout")
def checkout_cmd(
    at: str = typer.Argument(..., help="Valid time ISO 8601 to check out."),
    app_name: str = typer.Option(None, help="Limit to one app."),
    label: str = typer.Option(None, help="Optional label for the snapshot."),
) -> None:
    """Materialize and persist app state as of a time, like a git checkout."""
    config = load_config()
    store = open_store(config)
    try:
        valid = from_iso(at)
        snap = SnapshotMaterializer(store).materialize(
            app=app_name, as_of_valid=valid, as_of_ingest=valid, label=label
        )
        console.print(
            f"checked out {snap.snapshot_id} root {snap.root_hash[:12]} "
            f"with {snap.entity_count} entities"
        )
    finally:
        store.close()


@app.command("ls")
def ls_cmd(
    app_name: str = typer.Option(None, help="Limit to one app."),
    at: str = typer.Option(None, help="Valid time ISO 8601, defaults to latest."),
) -> None:
    """List the entities present as of a point in time."""
    config = load_config()
    store = open_store(config)
    try:
        es = EventStore(store.backend, store.blobs)
        valid = from_iso(at) if at else None
        states = list_entities(es, app=app_name, as_of_valid=valid)
        for s in states:
            console.print(f"{s.app}/{s.entity_type}/{s.entity_id}")
    finally:
        store.close()
