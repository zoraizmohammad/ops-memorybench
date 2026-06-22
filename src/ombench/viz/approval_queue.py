"""Human approval queue.

A privacy and trust surface: compiled memory candidates above a confidence floor but
below an auto accept threshold, or carrying privacy risk, are queued for human review
before they enter the mounted knowledge base. This gives a team control over what
durable knowledge the agent is trusted with, which matters because the memory is
compiled from real operational data.

The queue is backed by the relational store so approvals persist across sessions. A
candidate is pending until approved or rejected; only approved candidates are
compiled into active memory.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ids import new_id
from ..storage import Store
from ..timeutil import to_iso, utcnow


@dataclass
class ApprovalItem:
    approval_id: str
    claim: str
    namespace: str
    confidence: float
    acl: str
    status: str  # pending | approved | rejected
    reason: str = ""


# The approval queue reuses the sync_cursors table is not appropriate; it has its own
# small table created on demand so the extension is self contained.
_DDL = """
CREATE TABLE IF NOT EXISTS approval_queue (
    approval_id TEXT PRIMARY KEY,
    claim TEXT NOT NULL,
    namespace TEXT NOT NULL,
    confidence REAL NOT NULL,
    acl TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
)
"""


class ApprovalQueue:
    """A persisted human approval queue for risky memory candidates."""

    # Candidates with confidence at or above this are auto accepted; below the floor
    # they are dropped; in between, or any personal acl, they are queued for review.
    AUTO_ACCEPT = 0.85
    FLOOR = 0.4

    def __init__(self, store: Store) -> None:
        self.store = store
        self.store.backend.execute(_DDL)

    def needs_review(self, *, confidence: float, acl: str) -> bool:
        """Whether a candidate should be queued rather than auto handled."""
        if acl == "personal":
            return True
        return self.FLOOR <= confidence < self.AUTO_ACCEPT

    def enqueue(self, *, claim: str, namespace: str, confidence: float, acl: str, reason: str = "") -> str:
        approval_id = new_id("appr", seed={"claim": claim, "namespace": namespace})
        if self.store.backend.query_one(
            "SELECT approval_id FROM approval_queue WHERE approval_id = ?", (approval_id,)
        ):
            return approval_id
        self.store.backend.insert(
            "approval_queue",
            {
                "approval_id": approval_id,
                "claim": claim,
                "namespace": namespace,
                "confidence": confidence,
                "acl": acl,
                "status": "pending",
                "reason": reason,
                "created_at": to_iso(utcnow()),
            },
        )
        return approval_id

    def pending(self) -> list[ApprovalItem]:
        rows = self.store.backend.query(
            "SELECT * FROM approval_queue WHERE status = 'pending' ORDER BY created_at"
        )
        return [self._row(r) for r in rows]

    def decide(self, approval_id: str, *, approved: bool, reason: str = "") -> None:
        self.store.backend.execute(
            "UPDATE approval_queue SET status = ?, reason = ? WHERE approval_id = ?",
            ("approved" if approved else "rejected", reason, approval_id),
        )

    def approved(self) -> list[ApprovalItem]:
        rows = self.store.backend.query("SELECT * FROM approval_queue WHERE status = 'approved'")
        return [self._row(r) for r in rows]

    def _row(self, r: dict) -> ApprovalItem:
        return ApprovalItem(
            approval_id=r["approval_id"], claim=r["claim"], namespace=r["namespace"],
            confidence=r["confidence"], acl=r["acl"], status=r["status"], reason=r["reason"] or "",
        )
