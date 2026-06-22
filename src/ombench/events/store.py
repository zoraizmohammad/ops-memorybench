"""Append only bitemporal event log with fold materialization.

This module is the source of truth for app history. It implements the central
state equation of the platform:

    S(T, tau) = fold(S0, { e | valid_at(e) <= T and ingested_at(e) <= tau })

Events are only ever appended. State at a bitemporal point is computed by folding
the subset of events whose validity time is at or before ``T`` and whose ingestion
time is at or before ``tau``. The ingest time filter is what makes a backtest
honest: it reconstructs exactly what the system could have known at ``tau``, never
leaking information that arrived later.

The fold is deterministic. Events are ordered by ``valid_at`` then by the monotonic
ingest ``seq`` as a tie breaker, so two materializations of the same bitemporal
point always produce byte identical state.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..storage import StorageBackend
from ..storage.blobstore import BlobStore
from ..timeutil import ensure_utc, to_iso, utcnow
from .schema import App, AppEvent, Op


@dataclass
class EntityState:
    """The materialized current state of one entity at a bitemporal point.

    ``edges`` maps an edge kind to the set of live target ids, which is how
    membership and attendance style relationships are represented after the fold.
    ``deleted`` marks entities that were tombstoned as of the materialization
    point; they are kept so callers can distinguish "never existed" from "existed
    and was removed".
    """

    app: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    edges: dict[str, set[str]] = field(default_factory=dict)
    deleted: bool = False
    last_valid_at: datetime | None = None
    version_count: int = 0


class EventStore:
    """Persistence and querying for the canonical event log.

    Parameters
    ----------
    backend:
        Relational backend holding event rows.
    blobs:
        Content addressed store for normalized payloads and provenance records.
    """

    def __init__(self, backend: StorageBackend, blobs: BlobStore) -> None:
        self.backend = backend
        self.blobs = blobs

    # -- append -----------------------------------------------------------

    def _exists(self, event_id: str) -> bool:
        return (
            self.backend.query_one(
                "SELECT 1 AS x FROM app_events WHERE event_id = ?", (event_id,)
            )
            is not None
        )

    def append(self, event: AppEvent) -> str:
        """Append one event. Idempotent on ``event_id``.

        The payload and provenance are written to the blob store and only their
        hashes are kept on the row. A monotonic ``seq`` is assigned for stable
        tie breaking in the fold. Re appending an event with the same id is a no
        op, which keeps re ingestion safe.
        """
        if self._exists(event.event_id):
            return event.event_id

        payload_hash = self.blobs.put_json(event.payload) if event.payload else None
        provenance_hash = (
            self.blobs.put_json(event.provenance) if event.provenance else None
        )
        row = self.backend.query_one("SELECT COALESCE(MAX(seq), 0) AS m FROM app_events")
        next_seq = int(row["m"]) + 1 if row else 1

        self.backend.insert(
            "app_events",
            {
                "event_id": event.event_id,
                "app": event.app.value,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "op": event.op.value,
                "payload_hash": payload_hash,
                "valid_at": to_iso(event.valid_at),
                "ingested_at": to_iso(event.ingested_at),
                "actor_ref": event.actor_ref,
                "parent_entity_ref": event.parent_entity_ref,
                "source_cursor": event.source_cursor,
                "provenance_hash": provenance_hash,
                "seq": next_seq,
                # Edge endpoints are stored on the row as well so edge folds do
                # not need to load the payload blob.
                "edge_target": event.edge_target,
                "edge_kind": event.edge_kind,
            },
        )
        return event.event_id

    def append_many(self, events: Iterable[AppEvent]) -> int:
        """Append a batch of events in one transaction. Returns the count newly added."""
        added = 0
        with self.backend.transaction():
            for event in events:
                if not self._exists(event.event_id):
                    self.append(event)
                    added += 1
        return added

    # -- raw queries ------------------------------------------------------

    def count(self) -> int:
        row = self.backend.query_one("SELECT COUNT(*) AS c FROM app_events")
        return int(row["c"]) if row else 0

    def get_payload(self, event_id: str) -> dict[str, Any]:
        """Load the normalized payload for an event from the blob store."""
        row = self.backend.query_one(
            "SELECT payload_hash FROM app_events WHERE event_id = ?", (event_id,)
        )
        if not row or not row["payload_hash"]:
            return {}
        return self.blobs.get_json(row["payload_hash"])

    def iter_events(
        self,
        *,
        app: App | str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        as_of_valid: datetime | None = None,
        as_of_ingest: datetime | None = None,
        load_payload: bool = False,
    ) -> Iterator[dict[str, Any]]:
        """Yield event rows matching a bitemporal and entity filter, in fold order.

        Rows are ordered by ``valid_at`` then ``seq`` which is the canonical fold
        order. Set ``load_payload`` to attach the normalized payload from the blob
        store to each row under the ``payload`` key.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if app is not None:
            clauses.append("app = ?")
            params.append(App(app).value if not isinstance(app, str) else str(app))
        if entity_type is not None:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if entity_id is not None:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if as_of_valid is not None:
            clauses.append("valid_at <= ?")
            params.append(to_iso(ensure_utc(as_of_valid)))
        if as_of_ingest is not None:
            clauses.append("ingested_at <= ?")
            params.append(to_iso(ensure_utc(as_of_ingest)))

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM app_events{where} ORDER BY valid_at ASC, seq ASC"
        for row in self.backend.query(sql, params):
            if load_payload and row.get("payload_hash"):
                row = dict(row)
                row["payload"] = self.blobs.get_json(row["payload_hash"])
            yield row

    # -- fold materialization --------------------------------------------

    def materialize(
        self,
        *,
        app: App | str | None = None,
        as_of_valid: datetime | None = None,
        as_of_ingest: datetime | None = None,
        include_deleted: bool = False,
    ) -> dict[tuple[str, str, str], EntityState]:
        """Fold events into entity states at a bitemporal point.

        This is ``S(T, tau)``. With no time bounds it materializes the latest known
        state. With ``as_of_valid`` it reconstructs state as it was in the source
        app at that instant; additionally constraining ``as_of_ingest`` reconstructs
        what ombench could have known by that ingestion instant.

        Returns a mapping from entity key to :class:`EntityState`. Tombstoned
        entities are excluded unless ``include_deleted`` is set.
        """
        states: dict[tuple[str, str, str], EntityState] = {}
        for row in self.iter_events(
            app=app,
            as_of_valid=as_of_valid,
            as_of_ingest=as_of_ingest,
            load_payload=True,
        ):
            key = (row["app"], row["entity_type"], row["entity_id"])
            state = states.get(key)
            if state is None:
                state = EntityState(
                    app=row["app"],
                    entity_type=row["entity_type"],
                    entity_id=row["entity_id"],
                )
                states[key] = state
            self._apply(state, row)

        if include_deleted:
            return states
        return {k: v for k, v in states.items() if not v.deleted}

    @staticmethod
    def _apply(state: EntityState, row: dict[str, Any]) -> None:
        """Apply one event row to an entity state during the fold."""
        op = Op(row["op"])
        from ..timeutil import from_iso

        state.last_valid_at = from_iso(row["valid_at"])
        if op == Op.DELETE_ENTITY:
            state.deleted = True
            return
        if op == Op.UPSERT_EDGE:
            targets = state.edges.setdefault(row["edge_kind"], set())
            targets.add(row["edge_target"])
            return
        if op == Op.DELETE_EDGE:
            targets = state.edges.get(row["edge_kind"])
            if targets:
                targets.discard(row["edge_target"])
            return
        # All upsert style ops merge their payload into current state. A
        # reappearing entity clears a prior tombstone, matching real apps where an
        # id can be recreated.
        state.deleted = False
        payload = row.get("payload") or {}
        if op == Op.APPEND_VERSION:
            state.version_count += 1
        state.payload.update(payload)

    def materialize_entity(
        self,
        app: App | str,
        entity_type: str,
        entity_id: str,
        *,
        as_of_valid: datetime | None = None,
        as_of_ingest: datetime | None = None,
    ) -> EntityState | None:
        """Materialize a single entity at a bitemporal point, or ``None`` if absent."""
        state: EntityState | None = None
        for row in self.iter_events(
            app=app,
            entity_type=entity_type,
            entity_id=entity_id,
            as_of_valid=as_of_valid,
            as_of_ingest=as_of_ingest,
            load_payload=True,
        ):
            if state is None:
                state = EntityState(
                    app=row["app"], entity_type=row["entity_type"], entity_id=row["entity_id"]
                )
            self._apply(state, row)
        return state

    # -- cursors ----------------------------------------------------------

    def set_cursor(self, app: App | str, stream: str, cursor: str | None) -> None:
        """Persist the latest sync cursor for an app stream."""
        self.backend.insert(
            "sync_cursors",
            {
                "app": App(app).value if not isinstance(app, str) else str(app),
                "stream": stream,
                "cursor": cursor,
                "updated_at": to_iso(utcnow()),
            },
            replace=True,
        )

    def get_cursor(self, app: App | str, stream: str) -> str | None:
        app_val = App(app).value if not isinstance(app, str) else str(app)
        row = self.backend.query_one(
            "SELECT cursor FROM sync_cursors WHERE app = ? AND stream = ?",
            (app_val, stream),
        )
        return row["cursor"] if row else None
