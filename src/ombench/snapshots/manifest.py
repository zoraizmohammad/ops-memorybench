"""Snapshot manifest model.

A snapshot is a materialized point in time state root, the SaaS analogue of a git
commit. It records the bitemporal coordinates it was taken at, the set of entity
version hashes it covers, and a single Merkle style root hash over those, so two
snapshots of identical state share a root and a snapshot can be referenced cheaply
by hash rather than by duplicating content.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ..ids import content_hash, new_id, sha256_hex
from ..timeutil import to_iso


class EntityVersion(BaseModel):
    """One entity's materialized state and its content hash within a snapshot."""

    app: str
    entity_type: str
    entity_id: str
    version_hash: str
    deleted: bool = False


class SnapshotManifest(BaseModel):
    """A point in time state root over a set of entity versions."""

    snapshot_id: str = ""
    app: str | None = None
    as_of_valid_time: datetime
    as_of_ingest_time: datetime
    root_hash: str
    entities: list[EntityVersion] = Field(default_factory=list)
    label: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if not self.snapshot_id:
            seed = {
                "app": self.app,
                "valid": to_iso(self.as_of_valid_time),
                "ingest": to_iso(self.as_of_ingest_time),
                "root": self.root_hash,
            }
            object.__setattr__(self, "snapshot_id", new_id("snap", seed=seed))

    @property
    def entity_count(self) -> int:
        return len(self.entities)


def compute_root_hash(version_hashes: list[str]) -> str:
    """Compute a snapshot root from entity version hashes.

    The hashes are sorted then folded into a single SHA-256, so the root is order
    independent: the same set of entity versions always yields the same root,
    regardless of materialization order. An empty set has a well defined root.
    """
    if not version_hashes:
        return sha256_hex("ombench:empty-snapshot")
    return content_hash(sorted(version_hashes))


def version_hash(app: str, entity_type: str, entity_id: str, payload: dict, edges: dict, deleted: bool) -> str:
    """Content hash of one entity's normalized version within a snapshot.

    Edges are included as sorted lists so membership and attendance are part of the
    entity's identity at this point in time.
    """
    normalized = {
        "app": app,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "payload": payload,
        "edges": {k: sorted(v) for k, v in sorted(edges.items())},
        "deleted": deleted,
    }
    return content_hash(normalized)
