"""Time travel debugging view.

A demo surface for the history substrate: pick an entity and walk its state forward
through time, showing what changed at each step and which trajectory or sync produced
the change. This is the human facing window onto the bitemporal log, the thing that
makes "git for SaaS" click in a demo.

It produces an ordered timeline of an entity's states with the diff at each step, and
a workspace level activity timeline across all apps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..events.queries import entity_history, timeline
from ..events.store import EventStore


@dataclass
class TimelineFrame:
    """One step in an entity's life, with the fields that changed."""

    valid_at: datetime
    op: str
    changed: dict[str, Any] = field(default_factory=dict)
    full: dict[str, Any] = field(default_factory=dict)


def entity_timeline(
    store: EventStore, app: str, entity_type: str, entity_id: str
) -> list[TimelineFrame]:
    """Build a forward timeline of an entity, with the diff at each version."""
    history = entity_history(store, app, entity_type, entity_id)
    frames: list[TimelineFrame] = []
    accumulated: dict[str, Any] = {}
    for entry in history:
        changed: dict[str, Any] = {}
        for k, v in entry.payload.items():
            if accumulated.get(k) != v:
                changed[k] = v
        accumulated.update(entry.payload)
        frames.append(
            TimelineFrame(
                valid_at=entry.valid_at, op=entry.op,
                changed=changed, full=dict(accumulated),
            )
        )
    return frames


def workspace_activity(
    store: EventStore, *, start: datetime | None = None, end: datetime | None = None
) -> list[dict[str, Any]]:
    """A chronological activity feed across all apps in a window.

    Each entry names what changed and when, suitable for rendering as a scrubber in a
    time travel UI.
    """
    rows = timeline(store, start=start, end=end)
    feed: list[dict[str, Any]] = []
    for row in rows:
        feed.append(
            {
                "valid_at": row["valid_at"],
                "app": row["app"],
                "entity": f"{row['entity_type']}/{row['entity_id']}",
                "op": row["op"],
                "actor": row.get("actor_ref"),
            }
        )
    return feed


def render_timeline_text(frames: list[TimelineFrame]) -> str:
    """Render an entity timeline as readable text for the terminal."""
    lines: list[str] = []
    for i, f in enumerate(frames):
        changed = ", ".join(f"{k}={v}" for k, v in f.changed.items()) or "(no field change)"
        lines.append(f"[{i}] {f.valid_at.isoformat()} {f.op}: {changed}")
    return "\n".join(lines)
