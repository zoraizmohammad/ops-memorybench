"""Memory graph helpers.

Memory items and the entities they concern form a small graph: items link to each
other through supersedes, contradicts, supports, and derived_from edges, and they
attach to subjects (people, projects, teams). This module reads that graph for the
provenance viewer and for the retriever's one hop expansion, and computes simple
graph proximity used as a reranking feature.

The graph is derived from the append only ``memory_edges`` table, so it is always
consistent with the resolver's decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .store import MemoryStore


@dataclass
class MemoryNode:
    memory_id: str
    subject: str | None
    namespace: str
    neighbors: dict[str, list[str]] = field(default_factory=dict)


def neighbors(store: MemoryStore, memory_id: str, *, relations: tuple[str, ...] | None = None) -> list[str]:
    """Return neighbor memory ids reachable by the given relations."""
    out: list[str] = []
    for edge in store.edges_from(memory_id):
        if relations is None or edge["relation"] in relations:
            out.append(edge["dst_id"])
    return out


def proximity(store: MemoryStore, a_id: str, b_id: str, *, max_hops: int = 2) -> float:
    """A simple graph proximity score in 0..1 between two items.

    One hop apart scores high, two hops lower, unreachable scores zero. Used as the
    GraphProximity term in reranking when relating a candidate to an anchor item.
    """
    if a_id == b_id:
        return 1.0
    frontier = {a_id}
    visited = {a_id}
    for hop in range(1, max_hops + 1):
        nxt: set[str] = set()
        for node in frontier:
            for neighbor in neighbors(store, node):
                if neighbor == b_id:
                    return round(1.0 / (hop + 1), 4)
                if neighbor not in visited:
                    visited.add(neighbor)
                    nxt.add(neighbor)
        frontier = nxt
    return 0.0


def subjects_index(store: MemoryStore) -> dict[str, list[str]]:
    """Map each subject to the active memory ids about it.

    This is the people and projects view: every person or project subject and the
    knowledge attached to it, used by the provenance and diff viewers.
    """
    index: dict[str, list[str]] = {}
    for item in store.all_items(active_only=True):
        key = f"{item.namespace.value}:{item.subject or 'general'}"
        index.setdefault(key, []).append(item.memory_id)
    return index
