"""Deterministic simulated environment.

A sandbox is a fake SaaS stack seeded from a state snapshot that the agent can act
against as if it were the real app. The goal is not pixel perfect emulation; it is
semantic equivalence for the operations the benchmark uses. Reads return frozen
snapshot state; writes append to a sandbox event log rather than calling out; a
frozen clock prevents time from leaking.

The base :class:`Sandbox` holds the seeded state and the write log and wires up the
per app surfaces. Each integration provides a sandbox API (Slack, Calendar, Docs)
that reads from the seed and routes writes through :meth:`apply_write`, which records
them for the validators to inspect after a run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .clock import FrozenClock, clock_for_snapshot


@dataclass
class WriteAction:
    """One recorded write performed by the agent during replay."""

    app: str
    action: str
    payload: dict[str, Any]
    at: datetime
    result: dict[str, Any] = field(default_factory=dict)


class Sandbox:
    """A seeded, deterministic fake SaaS environment.

    Parameters
    ----------
    state:
        The materialized snapshot state, keyed by ``app/entity_type/entity_id`` as
        produced by :class:`~ombench.snapshots.SnapshotMaterializer`.
    as_of:
        The snapshot's valid time, used to freeze the clock.
    """

    def __init__(self, state: dict[str, Any], *, as_of: datetime) -> None:
        self.state = state
        self.clock: FrozenClock = clock_for_snapshot(as_of)
        self.writes: list[WriteAction] = []

    @property
    def now(self) -> datetime:
        return self.clock.now()

    # -- reads ------------------------------------------------------------

    def entities(self, app: str, entity_type: str) -> list[dict[str, Any]]:
        """Return the seeded entities of a given app and type."""
        prefix = f"{app}/{entity_type}/"
        out = []
        for key, value in self.state.items():
            if key.startswith(prefix) and not value.get("deleted"):
                out.append(value)
        return out

    def get_entity(self, app: str, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        value = self.state.get(f"{app}/{entity_type}/{entity_id}")
        if value is None or value.get("deleted"):
            return None
        return value

    def find_entity(self, app: str, entity_type: str, **match: Any) -> dict[str, Any] | None:
        """Find the first seeded entity whose payload matches all given fields."""
        for value in self.entities(app, entity_type):
            payload = value.get("payload", {})
            if all(payload.get(k) == v for k, v in match.items()):
                return value
        return None

    # -- writes -----------------------------------------------------------

    def apply_write(self, app: str, action: str, payload: dict[str, Any], result: dict[str, Any] | None = None) -> WriteAction:
        """Record a write action and return it.

        Writes never mutate the seeded read state; they accumulate in the log so the
        validators can inspect the resulting diff. A subsequent read in the same run
        still sees the original snapshot, which is the correct semantics for a
        single task replay.
        """
        record = WriteAction(
            app=app, action=action, payload=payload, at=self.now, result=result or {"ok": True}
        )
        self.writes.append(record)
        return record

    def writes_for(self, app: str) -> list[WriteAction]:
        return [w for w in self.writes if w.app == app]

    def reset(self) -> None:
        """Clear the write log so the sandbox can be reused for another condition."""
        self.writes = []
