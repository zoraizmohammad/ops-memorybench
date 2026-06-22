"""Persistence for compiled memory items and their edges.

Memory items are append only. Adding an item that duplicates an existing claim is a
no op; adding a contradictory or superseding item records an edge rather than
mutating the prior item. The ``active`` flag reflects the resolver's current view and
is the only field ever updated, and even that is a view decision rather than a
deletion: superseded items are retained for provenance.
"""

from __future__ import annotations

from ..storage import Store
from ..timeutil import to_iso, utcnow
from .schema import EdgeRelation, EvidenceRef, MemoryItem, MemoryType, Namespace, TTLPolicy


class MemoryStore:
    """Append only persistence for memory items and edges."""

    def __init__(self, store: Store) -> None:
        self.store = store

    # -- writes -----------------------------------------------------------

    def add(self, item: MemoryItem) -> str:
        """Persist a memory item. Idempotent on the content derived id."""
        backend = self.store.backend
        if backend.query_one("SELECT memory_id FROM memory_items WHERE memory_id = ?", (item.memory_id,)):
            return item.memory_id
        evidence_hash = (
            self.store.blobs.put_json([e.model_dump() for e in item.evidence])
            if item.evidence
            else None
        )
        backend.insert(
            "memory_items",
            {
                "memory_id": item.memory_id,
                "type": item.type.value,
                "namespace": item.namespace.value,
                "subject": item.subject,
                "claim": item.claim,
                "confidence": item.confidence,
                "ttl_policy": item.ttl_policy.value,
                "acl": item.acl,
                "evidence_hash": evidence_hash,
                "content_hash": item.content_hash,
                "created_at": to_iso(item.created_at),
                "valid_at": to_iso(item.valid_at) if item.valid_at else None,
                "active": 1 if item.active else 0,
            },
        )
        return item.memory_id

    def add_edge(self, src_id: str, dst_id: str, relation: EdgeRelation) -> None:
        self.store.backend.insert(
            "memory_edges",
            {
                "src_id": src_id,
                "dst_id": dst_id,
                "relation": relation.value,
                "created_at": to_iso(utcnow()),
            },
            replace=True,
        )

    def set_active(self, memory_id: str, active: bool) -> None:
        self.store.backend.execute(
            "UPDATE memory_items SET active = ? WHERE memory_id = ?",
            (1 if active else 0, memory_id),
        )

    # -- reads ------------------------------------------------------------

    def get(self, memory_id: str) -> MemoryItem | None:
        row = self.store.backend.query_one(
            "SELECT * FROM memory_items WHERE memory_id = ?", (memory_id,)
        )
        return self._row_to_item(row) if row else None

    def all_items(self, *, active_only: bool = False) -> list[MemoryItem]:
        sql = "SELECT * FROM memory_items"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY created_at ASC"
        return [self._row_to_item(r) for r in self.store.backend.query(sql)]

    def by_subject(self, namespace: Namespace, subject: str, *, active_only: bool = True) -> list[MemoryItem]:
        sql = "SELECT * FROM memory_items WHERE namespace = ? AND subject = ?"
        params = [namespace.value, subject]
        if active_only:
            sql += " AND active = 1"
        return [self._row_to_item(r) for r in self.store.backend.query(sql, params)]

    def edges_from(self, memory_id: str) -> list[dict]:
        return self.store.backend.query(
            "SELECT * FROM memory_edges WHERE src_id = ?", (memory_id,)
        )

    def _row_to_item(self, row: dict) -> MemoryItem:
        evidence: list[EvidenceRef] = []
        if row.get("evidence_hash"):
            evidence = [EvidenceRef(**e) for e in self.store.blobs.get_json(row["evidence_hash"])]
        from ..timeutil import from_iso

        return MemoryItem(
            memory_id=row["memory_id"],
            type=MemoryType(row["type"]),
            namespace=Namespace(row["namespace"]),
            subject=row["subject"],
            claim=row["claim"],
            confidence=row["confidence"],
            ttl_policy=TTLPolicy(row["ttl_policy"]),
            acl=row["acl"],
            evidence=evidence,
            created_at=from_iso(row["created_at"]),
            valid_at=from_iso(row["valid_at"]) if row["valid_at"] else None,
            active=bool(row["active"]),
        )
