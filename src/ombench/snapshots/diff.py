"""Snapshot diffing.

Comparing two snapshots reduces to comparing their per entity version hashes, which
is cheap because content addressing means equal content has equal hashes. This is
what powers a SaaS Git style ``diff`` between two points in time and the time travel
debugging view.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .manifest import SnapshotManifest


@dataclass
class SnapshotDiff:
    """The set of entities added, removed, or changed between two snapshots."""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unchanged: int = 0

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def summary(self) -> str:
        return (
            f"+{len(self.added)} added, -{len(self.removed)} removed, "
            f"~{len(self.changed)} changed, {self.unchanged} unchanged"
        )


def _key(app: str, entity_type: str, entity_id: str) -> str:
    return f"{app}/{entity_type}/{entity_id}"


def diff_snapshots(before: SnapshotManifest, after: SnapshotManifest) -> SnapshotDiff:
    """Diff two snapshot manifests by entity version hash.

    An entity present and live in only ``after`` is added; present and live in only
    ``before`` is removed; present in both with a different version hash is changed.
    Tombstoned entities are treated as not present for add and remove purposes so a
    deletion reads as a removal rather than a change.
    """
    def live_map(m: SnapshotManifest) -> dict[str, str]:
        return {
            _key(e.app, e.entity_type, e.entity_id): e.version_hash
            for e in m.entities
            if not e.deleted
        }

    bmap = live_map(before)
    amap = live_map(after)
    result = SnapshotDiff()

    for key, vh in amap.items():
        if key not in bmap:
            result.added.append(key)
        elif bmap[key] != vh:
            result.changed.append(key)
        else:
            result.unchanged += 1
    for key in bmap:
        if key not in amap:
            result.removed.append(key)

    result.added.sort()
    result.removed.sort()
    result.changed.sort()
    return result
