"""ombench.events subpackage.

The canonical append only bitemporal event log. :mod:`schema` defines the cross app
:class:`AppEvent` algebra, :mod:`algebra` provides readable constructors, and
:mod:`store` persists and queries events over a :class:`~ombench.storage.StorageBackend`.
"""

from __future__ import annotations

from . import algebra
from .schema import (
    DELETE_OPS,
    EDGE_OPS,
    UPSERT_OPS,
    App,
    AppEvent,
    Op,
)

__all__ = [
    "DELETE_OPS",
    "EDGE_OPS",
    "UPSERT_OPS",
    "App",
    "AppEvent",
    "Op",
    "algebra",
]
