"""Canonical app event schema.

Every integration normalizes its raw API payloads into a single cross app event
algebra. One algebra rather than per app scripts is what makes the history engine
universal: all change pathways can be rebuilt, replayed, and compacted the same way
regardless of which SaaS app produced them.

An :class:`AppEvent` is an immutable record of one mutation or observation. The two
time fields are the heart of the bitemporal model:

- ``valid_at``    when the change took effect in the source application
- ``ingested_at`` when ombench learned about it

Keeping both lets a backtest reconstruct state "as of T" and, crucially, "as of T
using only what had been ingested by tau", so a replay never sees information the
agent could not have had at the time.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..ids import content_hash, new_id
from ..timeutil import ensure_utc


class App(StrEnum):
    """Supported source applications."""

    SLACK = "slack"
    GCAL = "gcal"
    GDOCS = "gdocs"
    DRIVE = "drive"
    GMAIL = "gmail"


class Op(StrEnum):
    """The canonical operation vocabulary.

    These cover the change pathways needed across messaging, calendar, and
    document apps. Entities are nodes; edges are relationships such as channel
    membership or event attendance; versions capture content history such as a
    document export; permission and reaction and status changes are first class
    because they matter for operational reasoning.
    """

    UPSERT_ENTITY = "upsert_entity"
    DELETE_ENTITY = "delete_entity"
    UPSERT_EDGE = "upsert_edge"
    DELETE_EDGE = "delete_edge"
    APPEND_VERSION = "append_version"
    PERMISSION_CHANGE = "permission_change"
    COMMENT_ADD = "comment_add"
    REACTION_ADD = "reaction_add"
    STATUS_CHANGE = "status_change"


# Operations that create or update an entity's current state, as opposed to those
# that delete it. Used by the materializer's fold.
UPSERT_OPS = {
    Op.UPSERT_ENTITY,
    Op.APPEND_VERSION,
    Op.PERMISSION_CHANGE,
    Op.COMMENT_ADD,
    Op.REACTION_ADD,
    Op.STATUS_CHANGE,
}
DELETE_OPS = {Op.DELETE_ENTITY}
EDGE_OPS = {Op.UPSERT_EDGE, Op.DELETE_EDGE}


class AppEvent(BaseModel):
    """One normalized app mutation or observation.

    Instances are immutable. The ``payload`` is the normalized entity content; when
    persisted it is stored in the blob store and only its hash is kept on the event
    row. ``event_id`` is derived deterministically from the identifying fields and
    payload so that re ingesting the same change is idempotent.
    """

    model_config = ConfigDict(frozen=True)

    event_id: str = ""
    app: App
    entity_type: str
    entity_id: str
    op: Op
    payload: dict[str, Any] = Field(default_factory=dict)
    valid_at: datetime
    ingested_at: datetime
    actor_ref: str | None = None
    parent_entity_ref: str | None = None
    source_cursor: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    # Edge endpoints, only meaningful for edge operations.
    edge_target: str | None = None
    edge_kind: str | None = None

    def model_post_init(self, __context: Any) -> None:
        # Normalize times to aware UTC and derive a deterministic id if absent.
        object.__setattr__(self, "valid_at", ensure_utc(self.valid_at))
        object.__setattr__(self, "ingested_at", ensure_utc(self.ingested_at))
        if not self.event_id:
            object.__setattr__(self, "event_id", new_id("evt", seed=self._identity()))

    def _identity(self) -> dict[str, Any]:
        """The fields that define event identity for idempotent ingestion."""
        return {
            "app": self.app.value,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "op": self.op.value,
            "valid_at": self.valid_at,
            "payload_hash": self.payload_hash,
            "edge_target": self.edge_target,
            "edge_kind": self.edge_kind,
        }

    @property
    def payload_hash(self) -> str:
        """Content hash of the normalized payload."""
        return content_hash(self.payload)

    @property
    def is_edge(self) -> bool:
        return self.op in EDGE_OPS

    @property
    def is_delete(self) -> bool:
        return self.op in DELETE_OPS

    def entity_key(self) -> tuple[str, str, str]:
        """The (app, entity_type, entity_id) tuple that names an entity stream."""
        return (self.app.value, self.entity_type, self.entity_id)
