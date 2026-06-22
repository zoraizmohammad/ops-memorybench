"""Memory diff viewer.

Makes an evolving knowledge base legible by diffing two compiled states: what was
added, what was superseded or deactivated, and what changed. This is the memory
analogue of the snapshot diff, and it is what makes the knowledge base's evolution
visible during a demo rather than an opaque blob.

The diff compares two lists of memory items by their content derived id and active
flag, so it works on any two snapshots of the memory store.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..memory.schema import MemoryItem


@dataclass
class MemoryDiff:
    added: list[MemoryItem] = field(default_factory=list)
    removed: list[MemoryItem] = field(default_factory=list)  # deactivated or deleted
    reactivated: list[MemoryItem] = field(default_factory=list)
    unchanged: int = 0

    def summary(self) -> str:
        return (
            f"+{len(self.added)} added, -{len(self.removed)} deactivated, "
            f"{len(self.reactivated)} reactivated, {self.unchanged} unchanged"
        )

    def to_markdown(self) -> str:
        lines = ["# Memory diff", "", self.summary(), ""]
        if self.added:
            lines.append("## Added")
            lines += [f"- ({m.type.value}) {m.claim}" for m in self.added]
            lines.append("")
        if self.removed:
            lines.append("## Deactivated")
            lines += [f"- ({m.type.value}) {m.claim}" for m in self.removed]
            lines.append("")
        return "\n".join(lines).strip()


def diff_memory(before: list[MemoryItem], after: list[MemoryItem]) -> MemoryDiff:
    """Diff two snapshots of the memory store by id and active flag."""
    before_by_id = {m.memory_id: m for m in before}
    after_by_id = {m.memory_id: m for m in after}
    diff = MemoryDiff()

    for mid, m in after_by_id.items():
        prev = before_by_id.get(mid)
        if prev is None:
            diff.added.append(m)
        elif prev.active and not m.active:
            diff.removed.append(m)
        elif not prev.active and m.active:
            diff.reactivated.append(m)
        else:
            diff.unchanged += 1
    for mid, m in before_by_id.items():
        if mid not in after_by_id:
            diff.removed.append(m)
    return diff
