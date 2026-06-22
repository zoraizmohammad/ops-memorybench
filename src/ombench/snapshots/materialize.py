"""Snapshot materializer.

Folds the event log into a point in time state and persists it as a content
addressed :class:`SnapshotManifest`, the SaaS analogue of a git commit. This is the
acceleration structure described by event sourcing: the log is the source of truth,
snapshots are fast reconstructions you can reference and diff cheaply.

A materialized snapshot stores:

- the full normalized state as a single blob, addressed by the snapshot root
- a manifest row in the relational store, addressed by ``snapshot_id``
- per entity version hashes, so two snapshots can be diffed without reloading content
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..events.store import EventStore
from ..storage import Store
from ..timeutil import to_iso, utcnow
from .manifest import (
    EntityVersion,
    SnapshotManifest,
    compute_root_hash,
    version_hash,
)


class SnapshotMaterializer:
    """Materializes and persists point in time snapshots from the event log."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.events = EventStore(store.backend, store.blobs)

    def materialize(
        self,
        *,
        app: str | None = None,
        as_of_valid: datetime | None = None,
        as_of_ingest: datetime | None = None,
        label: str | None = None,
        persist: bool = True,
    ) -> SnapshotManifest:
        """Build a snapshot at a bitemporal point and optionally persist it.

        ``as_of_valid`` defaults to now and ``as_of_ingest`` to now, which yields the
        latest known state. Both can be set to reconstruct historical state under
        the bitemporal model.
        """
        valid = as_of_valid or utcnow()
        ingest = as_of_ingest or utcnow()
        states = self.events.materialize(
            app=app,
            as_of_valid=valid,
            as_of_ingest=ingest,
            include_deleted=True,
        )

        entities: list[EntityVersion] = []
        full_state: dict[str, Any] = {}
        for key in sorted(states.keys()):
            state = states[key]
            vh = version_hash(
                state.app, state.entity_type, state.entity_id,
                state.payload, state.edges, state.deleted,
            )
            entities.append(
                EntityVersion(
                    app=state.app, entity_type=state.entity_type,
                    entity_id=state.entity_id, version_hash=vh, deleted=state.deleted,
                )
            )
            full_state[f"{state.app}/{state.entity_type}/{state.entity_id}"] = {
                "payload": state.payload,
                "edges": {k: sorted(v) for k, v in state.edges.items()},
                "deleted": state.deleted,
                "version_hash": vh,
            }

        root = compute_root_hash([e.version_hash for e in entities])
        manifest = SnapshotManifest(
            app=app,
            as_of_valid_time=valid,
            as_of_ingest_time=ingest,
            root_hash=root,
            entities=entities,
            label=label,
        )

        if persist:
            self._persist(manifest, full_state)
        return manifest

    def _persist(self, manifest: SnapshotManifest, full_state: dict[str, Any]) -> None:
        # The full normalized state blob is addressed by the snapshot root, so two
        # identical snapshots share one blob.
        state_hash = self.store.blobs.put_json(full_state)
        manifest_hash = self.store.blobs.put_json(manifest.model_dump(mode="json"))
        self.store.backend.insert(
            "snapshot_manifests",
            {
                "snapshot_id": manifest.snapshot_id,
                "app": manifest.app,
                "as_of_valid_time": to_iso(manifest.as_of_valid_time),
                "as_of_ingest_time": to_iso(manifest.as_of_ingest_time),
                "root_hash": manifest.root_hash,
                "manifest_hash": manifest_hash,
                "entity_count": manifest.entity_count,
                "created_at": to_iso(utcnow()),
                "label": manifest.label,
            },
            replace=True,
        )
        # Stash the state blob hash on the manifest blob mapping for retrieval.
        self.store.backend.insert(
            "sync_cursors",
            {
                "app": "_snapshot_state",
                "stream": manifest.snapshot_id,
                "cursor": state_hash,
                "updated_at": to_iso(utcnow()),
            },
            replace=True,
        )

    # -- retrieval --------------------------------------------------------

    def load_state(self, snapshot_id: str) -> dict[str, Any]:
        """Load the full normalized state blob for a persisted snapshot."""
        row = self.store.backend.query_one(
            "SELECT cursor FROM sync_cursors WHERE app = '_snapshot_state' AND stream = ?",
            (snapshot_id,),
        )
        if not row or not row["cursor"]:
            return {}
        return self.store.blobs.get_json(row["cursor"])

    def get_manifest(self, snapshot_id: str) -> SnapshotManifest | None:
        row = self.store.backend.query_one(
            "SELECT manifest_hash FROM snapshot_manifests WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        if not row:
            return None
        doc = self.store.blobs.get_json(row["manifest_hash"])
        return SnapshotManifest.model_validate(doc)

    def list_snapshots(self) -> list[dict[str, Any]]:
        return self.store.backend.query(
            "SELECT snapshot_id, app, as_of_valid_time, root_hash, entity_count, label "
            "FROM snapshot_manifests ORDER BY created_at DESC"
        )
