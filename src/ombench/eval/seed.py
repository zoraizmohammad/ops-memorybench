"""Loading a curated memory seed into the store.

The benchmark ships a curated knowledge base seed representing the durable memory a
team would have compiled from its history. Loading it lets the backtest run against a
known, reviewable set of memory items rather than depending only on what the small
fixture trajectories happen to surface. In production this same store is filled by the
compiler from real trajectories; the seed is the reviewable stand in for the demo.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ..memory.schema import MemoryItem, MemoryType, Namespace
from ..memory.store import MemoryStore
from ..storage import Store


def load_memory_seed(store: Store, path: str | Path) -> int:
    """Load curated memory items from a YAML seed into the store. Returns the count."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    mstore = MemoryStore(store)
    count = 0
    for raw in data.get("items", []):
        item = MemoryItem(
            type=MemoryType(raw.get("type", "semantic")),
            namespace=Namespace(raw.get("namespace", "team")),
            subject=raw.get("subject"),
            claim=raw["claim"],
            confidence=float(raw.get("confidence", 0.7)),
            acl=raw.get("acl", "team"),
            tags=["seed"],
        )
        mstore.add(item)
        count += 1
    return count
