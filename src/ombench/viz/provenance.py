"""Provenance graph viewer.

Every memory item carries evidence references back to the trajectories, events, and
snapshots it was derived from, plus edges to items it supersedes or contradicts. This
renders that provenance as a graph so a reviewer can see, for any memory, exactly why
it is believed and what it relates to. It is the trust surface of the knowledge base.

The graph is emitted both as a plain text tree and as Graphviz DOT, so it can be
viewed in a terminal or rendered to an image.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..memory.schema import MemoryItem
from ..memory.store import MemoryStore


@dataclass
class ProvenanceNode:
    memory_id: str
    claim: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    contradicts: list[str] = field(default_factory=list)


def build_provenance(store: MemoryStore, memory_id: str) -> ProvenanceNode | None:
    """Build the provenance node for one memory item."""
    item = store.get(memory_id)
    if item is None:
        return None
    edges = store.edges_from(memory_id)
    return ProvenanceNode(
        memory_id=item.memory_id,
        claim=item.claim,
        confidence=item.confidence,
        evidence=[f"{e.kind}:{e.ref}" for e in item.evidence],
        supersedes=[e["dst_id"] for e in edges if e["relation"] == "supersedes"],
        contradicts=[e["dst_id"] for e in edges if e["relation"] == "contradicts"],
    )


def to_text(node: ProvenanceNode) -> str:
    """Render a provenance node as an indented text tree."""
    lines = [f"{node.memory_id} (confidence {node.confidence})", f"  claim: {node.claim}"]
    if node.evidence:
        lines.append("  evidence:")
        lines += [f"    - {e}" for e in node.evidence]
    if node.supersedes:
        lines.append("  supersedes: " + ", ".join(node.supersedes))
    if node.contradicts:
        lines.append("  contradicts: " + ", ".join(node.contradicts))
    return "\n".join(lines)


def to_dot(store: MemoryStore) -> str:
    """Render the whole memory graph as Graphviz DOT.

    Items are nodes labeled with their claim; evidence and edges are arrows. This is
    a complete provenance graph of the knowledge base suitable for rendering.
    """
    lines = ["digraph provenance {", "  rankdir=LR;", '  node [shape=box];']
    items: list[MemoryItem] = store.all_items()
    for item in items:
        label = item.claim.replace('"', "'")[:48]
        color = "black" if item.active else "gray"
        lines.append(f'  "{item.memory_id}" [label="{label}", color={color}];')
        for e in item.evidence:
            ev_id = f"{e.kind}:{e.ref}"
            lines.append(f'  "{ev_id}" [shape=note, color=blue];')
            lines.append(f'  "{ev_id}" -> "{item.memory_id}" [label="evidence"];')
        for edge in store.edges_from(item.memory_id):
            lines.append(
                f'  "{item.memory_id}" -> "{edge["dst_id"]}" [label="{edge["relation"]}"];'
            )
    lines.append("}")
    return "\n".join(lines)
