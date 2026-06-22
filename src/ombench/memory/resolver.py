"""Contradiction detection and active view resolution.

Memory is append only, so when two items make competing claims about the same
subject the system does not overwrite one. Instead it records a ``contradicts`` or
``supersedes`` edge and marks the losing item inactive. The active view is chosen by
a deterministic priority: higher confidence wins, ties break toward the more recent
item, then toward the more reliable acl scope. Provenance is always retained.

Contradiction detection here is intentionally conservative and rule based. Two items
contradict when they share a subject and namespace and express opposing polarity
about the same topic, detected via negation cues and high lexical overlap. A
production system would layer an entailment model on top; the structured decision and
the append only policy are what matter and are fully implemented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import EdgeRelation, MemoryItem
from .store import MemoryStore

_NEGATION = re.compile(r"\b(?:not|never|no longer|avoid|don't|do not|stop)\b", re.IGNORECASE)
_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def _polarity(text: str) -> bool:
    """True for positive polarity, False if a negation cue is present."""
    return _NEGATION.search(text) is None


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def contradicts(a: MemoryItem, b: MemoryItem, *, overlap_threshold: float = 0.5) -> bool:
    """Heuristic contradiction test between two items about the same subject.

    They must share namespace and subject, have opposing polarity, and share enough
    content tokens to be about the same topic.
    """
    if a.namespace != b.namespace or (a.subject or "") != (b.subject or ""):
        return False
    if a.memory_id == b.memory_id:
        return False
    ta, tb = _tokens(a.claim), _tokens(b.claim)
    # Compare content words ignoring the negation tokens themselves.
    content_overlap = jaccard(ta - _stop(), tb - _stop())
    return _polarity(a.claim) != _polarity(b.claim) and content_overlap >= overlap_threshold


def _stop() -> set[str]:
    return {"not", "never", "no", "longer", "avoid", "don", "do", "stop", "t", "the", "a", "to", "is", "and"}


@dataclass
class ResolutionResult:
    active_id: str
    inactivated: list[str]
    relation: EdgeRelation


def resolve_pair(store: MemoryStore, a: MemoryItem, b: MemoryItem) -> ResolutionResult:
    """Resolve a contradicting pair, recording an edge and the active view.

    The winner is the higher confidence item; ties go to the more recent one, then
    to the more privileged acl. The loser is marked inactive and a ``supersedes``
    edge points from winner to loser.
    """
    winner, loser = _rank(a, b)
    store.add_edge(winner.memory_id, loser.memory_id, EdgeRelation.SUPERSEDES)
    store.add_edge(loser.memory_id, winner.memory_id, EdgeRelation.CONTRADICTS)
    store.set_active(loser.memory_id, False)
    store.set_active(winner.memory_id, True)
    return ResolutionResult(
        active_id=winner.memory_id,
        inactivated=[loser.memory_id],
        relation=EdgeRelation.SUPERSEDES,
    )


_ACL_PRIORITY = {"personal": 3, "project": 2, "team": 1}


def _rank(a: MemoryItem, b: MemoryItem) -> tuple[MemoryItem, MemoryItem]:
    """Return (winner, loser) by confidence then recency then acl priority."""
    def key(item: MemoryItem):
        return (
            item.confidence,
            item.created_at,
            _ACL_PRIORITY.get(item.acl, 0),
        )

    if key(a) >= key(b):
        return a, b
    return b, a


def resolve_all(store: MemoryStore) -> list[ResolutionResult]:
    """Scan all items and resolve every detected contradiction.

    Runs after compilation so the active view reflects the latest, most trustworthy
    claim for each subject while every prior claim is retained with edges.
    """
    items = store.all_items()
    results: list[ResolutionResult] = []
    # Group by (namespace, subject) to limit pairwise comparisons.
    groups: dict[tuple[str, str], list[MemoryItem]] = {}
    for item in items:
        groups.setdefault((item.namespace.value, item.subject or ""), []).append(item)

    for group in groups.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if contradicts(group[i], group[j]):
                    results.append(resolve_pair(store, group[i], group[j]))
    return results
