"""``omb sync`` and ``omb snapshot`` command groups.

Operator commands for Task 2: pull SaaS state into the bitemporal event log and
materialize point in time snapshots. With no credentials these run against the
bundled synthetic fixtures, so the whole substrate is exercisable offline.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ..config import load_config
from ..events.queries import stats as event_stats
from ..events.store import EventStore
from ..integrations.gcal.sync import GCalSync
from ..integrations.gdocs.sync import GDocsSync
from ..integrations.slack.sync import SlackSync
from ..snapshots import SnapshotMaterializer, diff_snapshots
from ..storage import open_store
from ..timeutil import from_iso

sync_app = typer.Typer(help="Sync SaaS state into the event log.", no_args_is_help=True)
snapshot_app = typer.Typer(help="Materialize and inspect snapshots.", no_args_is_help=True)
console = Console()

_INTEGRATIONS = {"slack": SlackSync, "gcal": GCalSync, "gdocs": GDocsSync}
_FIXTURE_FILES = {
    "slack": ("slack", "workspace.json"),
    "gcal": ("gcal", "calendar.json"),
    "gdocs": ("gdocs", "docs.json"),
}


def _build_integration(name: str, store, config):
    cls = _INTEGRATIONS[name]
    sub, fname = _FIXTURE_FILES[name]
    fixtures_path = config.fixtures_dir / sub / fname
    return cls(EventStore(store.backend, store.blobs), fixtures_path=fixtures_path)


@sync_app.command("run")
def sync_run(
    app: str = typer.Argument("all", help="all | slack | gcal | gdocs"),
) -> None:
    """Run a sync for one app or all apps from fixtures or live credentials."""
    config = load_config()
    store = open_store(config)
    try:
        names = list(_INTEGRATIONS) if app == "all" else [app]
        for name in names:
            integ = _build_integration(name, store, config)
            result = integ.run_sync()
            mode = "live" if integ.is_live else "fixtures"
            console.print(
                f"{name} sync via {mode} emitted {result.events_emitted} new {result.events_new}"
            )
    finally:
        store.close()


@sync_app.command("stats")
def sync_stats() -> None:
    """Show summary statistics over the event log."""
    config = load_config()
    store = open_store(config)
    try:
        s = event_stats(EventStore(store.backend, store.blobs))
        console.print(f"total events {s['total']}")
        console.print(f"by app {s['by_app']}")
        console.print(f"by op {s['by_op']}")
        console.print(f"valid range {s['valid_range']}")
    finally:
        store.close()


@snapshot_app.command("create")
def snapshot_create(
    app: str = typer.Option(None, help="Limit to one app."),
    as_of: str = typer.Option(None, help="Valid time ISO 8601, defaults to now."),
    label: str = typer.Option(None, help="Optional label."),
) -> None:
    """Materialize a point in time snapshot and persist it."""
    config = load_config()
    store = open_store(config)
    try:
        valid = from_iso(as_of) if as_of else None
        mat = SnapshotMaterializer(store)
        snap = mat.materialize(app=app, as_of_valid=valid, as_of_ingest=valid, label=label)
        console.print(
            f"snapshot {snap.snapshot_id} root {snap.root_hash[:12]} "
            f"entities {snap.entity_count}"
        )
    finally:
        store.close()


@snapshot_app.command("list")
def snapshot_list() -> None:
    """List persisted snapshots."""
    config = load_config()
    store = open_store(config)
    try:
        table = Table(title="snapshots")
        table.add_column("snapshot_id")
        table.add_column("app")
        table.add_column("as of valid")
        table.add_column("root")
        table.add_column("entities")
        table.add_column("label")
        for s in SnapshotMaterializer(store).list_snapshots():
            table.add_row(
                s["snapshot_id"], s["app"] or "all", s["as_of_valid_time"],
                s["root_hash"][:12], str(s["entity_count"]), s["label"] or "",
            )
        console.print(table)
    finally:
        store.close()


@snapshot_app.command("diff")
def snapshot_diff(
    before: str = typer.Argument(...),
    after: str = typer.Argument(...),
) -> None:
    """Diff two persisted snapshots by id."""
    config = load_config()
    store = open_store(config)
    try:
        mat = SnapshotMaterializer(store)
        b = mat.get_manifest(before)
        a = mat.get_manifest(after)
        if b is None or a is None:
            console.print("[red]one or both snapshots not found[/red]")
            raise typer.Exit(code=1)
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
