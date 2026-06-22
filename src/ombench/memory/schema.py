"""Memory item schema.

A :class:`MemoryItem` is a durable, compiled unit of knowledge. The taxonomy follows
the agent memory literature: episodic (specific past events and outcomes), semantic
(stable facts, preferences, norms, contacts, project context), and procedural
(reusable workflows and how we do things). Each item carries a namespace that routes
it to a scope (user, team, project, app state), an explicit confidence, evidence
references back to the trajectories or snapshots it was derived from, a TTL policy for
forgetting, and an ACL for privacy separation.

The cardinal policy is that memory items are immutable. A claim is never overwritten
in place. Contradictions are represented by edges between items, and a resolver picks
the active view. This mirrors append only and bitemporal history design: actual
knowledge may be revised, but the record of what was believed is append only.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..ids import content_hash, new_id
from ..timeutil import ensure_utc, utcnow


class MemoryType(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class Namespace(StrEnum):
    USER = "user"
    TEAM = "team"
    PROJECT = "project"
    APP_STATE = "app_state"


class TTLPolicy(StrEnum):
    """Class specific forgetting policies rather than one global expiry.

    Durable knowledge persists where it matters and transient cues decay, which keeps
    the mounted knowledge base from filling with stale noise.
    """

    NEVER = "never"  # explicit personal preference, only contradiction or deletion removes it
    LONG = "long"  # team norm, periodic reconfirmation
    MEDIUM = "medium"  # project fact, decays after inactivity or archive
    SHORT = "short"  # transient operational cue


class EdgeRelation(StrEnum):
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    SUPPORTS = "supports"
    DERIVED_FROM = "derived_from"


class EvidenceRef(BaseModel):
    """A pointer from a memory item to the evidence it was derived from."""

    model_config = ConfigDict(frozen=True)

    kind: str  # trace | span | event | snapshot | document
    ref: str  # id or blob reference
    note: str | None = None


class MemoryItem(BaseModel):
    """A durable compiled unit of knowledge."""

    model_config = ConfigDict(frozen=True)

    memory_id: str = ""
    type: MemoryType
    namespace: Namespace
    subject: str | None = None
    claim: str
    confidence: float = 0.5
    ttl_policy: TTLPolicy = TTLPolicy.MEDIUM
    acl: str = "team"  # personal | team | project
    evidence: list[EvidenceRef] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    valid_at: datetime | None = None
    # Resolver flag, not a deletion. Superseded or contradicted items become inactive
    # but are retained for provenance.
    active: bool = True

    def model_post_init(self, __context: Any) -> None:
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        if self.valid_at is not None:
            object.__setattr__(self, "valid_at", ensure_utc(self.valid_at))
        if not self.memory_id:
            object.__setattr__(self, "memory_id", new_id("mem", seed=self.dedupe_key()))

    def dedupe_key(self) -> dict[str, Any]:
        """The identity used to deduplicate equivalent claims.

        Two items with the same type, namespace, subject, and normalized claim are
        the same knowledge and should collapse to one id.
        """
        return {
            "type": self.type.value,
            "namespace": self.namespace.value,
            "subject": (self.subject or "").strip().lower(),
            "claim": self.claim.strip().lower(),
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.dedupe_key())
