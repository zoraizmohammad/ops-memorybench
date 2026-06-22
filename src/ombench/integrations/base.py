"""Integration base interfaces.

Every SaaS integration implements the same small contract so the history engine is
universal rather than a collection of one off scripts. An integration has three
responsibilities:

- **sync**: pull data from the source (live API or synthetic fixtures) and yield
  canonical :class:`~ombench.events.schema.AppEvent` objects, persisting sync cursors
  so incremental sync can resume.
- **normalize**: map raw API payloads to the normalized entity payloads carried by
  events. This is where app specific shapes become the cross app vocabulary.
- **sandbox_api**: expose a deterministic read and write surface seeded from a
  snapshot, used by the replay environment.

The base class wires an integration to the event store and a clock, and provides a
``run_sync`` helper that appends yielded events. Concrete integrations override
:meth:`sync` and declare which entity types they produce.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from ..events.schema import App, AppEvent
from ..events.store import EventStore
from ..timeutil import Clock, utcnow


class SyncResult:
    """Summary of one sync run."""

    def __init__(self) -> None:
        self.events_emitted = 0
        self.events_new = 0
        self.cursors: dict[str, str | None] = {}

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"SyncResult(emitted={self.events_emitted}, new={self.events_new}, "
            f"cursors={self.cursors})"
        )


class Integration(ABC):
    """Base class for a SaaS integration.

    Parameters
    ----------
    store:
        The event store events are appended to.
    clock:
        Source of the ingestion time stamped onto emitted events. A frozen clock
        makes a sync run reproducible, which the tests rely on.
    fixtures:
        Optional synthetic data source. When live credentials are absent the
        integration reads from here, which is the keyless default path.
    """

    #: Stable application identifier, set by subclasses.
    app: App

    #: Entity types this integration can produce, for documentation and validation.
    entity_types: tuple[str, ...] = ()

    def __init__(
        self,
        store: EventStore,
        *,
        clock: Clock | None = None,
        fixtures: Any | None = None,
    ) -> None:
        self.store = store
        self.clock = clock or Clock()
        self.fixtures = fixtures

    # -- the contract -----------------------------------------------------

    @abstractmethod
    def sync(self, *, ingested_at: datetime) -> Iterator[AppEvent]:
        """Yield canonical events for everything observed in this sync.

        ``ingested_at`` is the time the platform is learning this data, stamped onto
        every emitted event so the bitemporal model is honest. Implementations read
        the source (live or fixtures), persist sync cursors via the event store, and
        yield one event per observed change.
        """
        raise NotImplementedError

    @property
    def is_live(self) -> bool:
        """Whether this integration is configured to use live credentials.

        The base implementation is fixture based. Live subclasses override this to
        reflect credential presence.
        """
        return False

    # -- driver -----------------------------------------------------------

    def run_sync(self, *, ingested_at: datetime | None = None) -> SyncResult:
        """Execute one sync, appending all yielded events to the store.

        Returns a :class:`SyncResult` summarizing how many events were emitted and
        how many were newly appended (re sync is idempotent thanks to deterministic
        event ids).
        """
        ts = ingested_at or self.clock.now()
        result = SyncResult()
        for event in self.sync(ingested_at=ts):
            result.events_emitted += 1
            before = self.store.count()
            self.store.append(event)
            if self.store.count() > before:
                result.events_new += 1
        return result


class IntegrationSandbox(ABC):
    """Base class for a deterministic sandbox API seeded from a snapshot.

    A sandbox presents a read and write surface that behaves like the real app for
    the operations the benchmark uses, but reads come from a frozen materialized
    snapshot and writes append to a local sandbox log rather than calling out. This
    is what lets the backtest run an agent against historical state safely.
    """

    app: App

    def __init__(self, seed_state: dict[str, Any], *, now: datetime | None = None) -> None:
        self.seed_state = seed_state
        self.now = now or utcnow()
        # Writes are recorded here so validators can inspect the resulting diff.
        self.writes: list[dict[str, Any]] = []

    def record_write(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Record a write action against the sandbox and return a fake ok response."""
        entry = {"action": action, "payload": payload, "at": self.now}
        self.writes.append(entry)
        return {"ok": True, "action": action}
