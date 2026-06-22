"""ombench.snapshots subpackage.

Point in time state materialization, the SaaS analogue of a git commit. The
:class:`SnapshotMaterializer` folds the event log into a content addressed
:class:`SnapshotManifest`, and :func:`diff_snapshots` compares two of them cheaply by
entity version hash.
"""

from __future__ import annotations

from .diff import SnapshotDiff, diff_snapshots
from .manifest import (
    EntityVersion,
    SnapshotManifest,
    compute_root_hash,
    version_hash,
)
from .materialize import SnapshotMaterializer

__all__ = [
    "EntityVersion",
    "SnapshotDiff",
    "SnapshotManifest",
    "SnapshotMaterializer",
    "compute_root_hash",
    "diff_snapshots",
    "version_hash",
]
