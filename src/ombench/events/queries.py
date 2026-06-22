"""Higher level query helpers over the event log.

These build on :class:`~ombench.events.store.EventStore` to answer the questions
that the snapshot materializer, memory compiler, and time travel tooling need:
what entities exist at a point in time, what an entity's full version history is,
what happened in a time window, and summary statistics over the log.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..timeutil import from_iso
from .schema import App
from .store import EntityState, EventStore


@dataclass
class HistoryEntry:
    """One observed version of an entity in its history."""

    valid_at: datetime
    ingested_at: datetime
    op: str
    payload: dict[str, Any]
    event_id: str


def entity_history(
    store: EventStore,
    app: App | str,
    entity_type: str,
    entity_id: str,
    *,
    as_of_ingest: datetime | None = None,
) -> list[HistoryEntry]:
    """Return the full ordered version history of one entity.

    This is the data behind a time travel diff view: every change that touched the
    entity, oldest first. Constraining ``as_of_ingest`` yields the history as it was
    known at a given ingestion time.
    """
    entries: list[HistoryEntry] = []
    for row in store.iter_events(
        app=app,
        entity_type=entity_type,
        entity_id=entity_id,
        as_of_ingest=as_of_ingest,
        load_payload=True,
    ):
        entries.append(
            HistoryEntry(
                valid_at=from_iso(row["valid_at"]),
                ingested_at=from_iso(row["ingested_at"]),
                op=row["op"],
                payload=row.get("payload") or {},
                event_id=row["event_id"],
            )
        )
    return entries


def list_entities(
    store: EventStore,
    *,
    app: App | str | None = None,
    entity_type: str | None = None,
    as_of_valid: datetime | None = None,
    as_of_ingest: datetime | None = None,
    include_deleted: bool = False,
) -> list[EntityState]:
    """Return materialized entity states at a bitemporal point, optionally filtered.

    Results are sorted by entity key for stable, reproducible output.
    """
    states = store.materialize(
        app=app,
        as_of_valid=as_of_valid,
        as_of_ingest=as_of_ingest,
        include_deleted=include_deleted,
    )
    result = list(states.values())
    if entity_type is not None:
        result = [s for s in result if s.entity_type == entity_type]
    result.sort(key=lambda s: (s.app, s.entity_type, s.entity_id))
    return result


def timeline(
    store: EventStore,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    app: App | str | None = None,
    as_of_ingest: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return events whose valid time falls in a window, in chronological order.

    Powers "what happened on day X" style summaries used by episodic memory
    extraction and the timeline KB files.
    """
    rows: list[dict[str, Any]] = []
    for row in store.iter_events(app=app, as_of_valid=end, as_of_ingest=as_of_ingest):
        if start is not None and from_iso(row["valid_at"]) < start:
            continue
        rows.append(row)
    return rows


def stats(store: EventStore) -> dict[str, Any]:
    """Return summary counts over the event log for dashboards and sanity checks."""
    by_app = store.backend.query(
        "SELECT app, COUNT(*) AS c FROM app_events GROUP BY app ORDER BY app"
    )
    by_op = store.backend.query(
        "SELECT op, COUNT(*) AS c FROM app_events GROUP BY op ORDER BY op"
    )
    bounds = store.backend.query_one(
        "SELECT MIN(valid_at) AS min_valid, MAX(valid_at) AS max_valid, "
        "MIN(ingested_at) AS min_ingest, MAX(ingested_at) AS max_ingest FROM app_events"
    )
    return {
        "total": store.count(),
        "by_app": {r["app"]: r["c"] for r in by_app},
        "by_op": {r["op"]: r["c"] for r in by_op},
        "valid_range": (bounds["min_valid"], bounds["max_valid"]) if bounds else (None, None),
        "ingest_range": (bounds["min_ingest"], bounds["max_ingest"]) if bounds else (None, None),
    }
