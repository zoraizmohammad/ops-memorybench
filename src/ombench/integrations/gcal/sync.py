"""Google Calendar sync adapter.

Models the documented Calendar incremental sync protocol: a full sync establishes a
``nextSyncToken``; subsequent incremental syncs pass the stored token and receive
only changes since then, including cancellations; if the server responds ``410
GONE`` the local token is invalid and a full resync is required.

The adapter consumes batches of events. Each batch carries the events visible at one
sync step and the ``sync_token`` the server would return. The stored cursor is the
last token consumed, so re running picks up only newer batches. A cancelled event
(``status == "cancelled"``) is emitted as a delete so the deletion is preserved in
history, never silently hidden.

The valid time of each emitted event is its ``updated`` timestamp, which is when the
change took effect in Calendar. That is what makes valid time travel faithful: a
reschedule that happened at 5pm is only visible in materializations as of 5pm or
later.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from ...events import algebra
from ...events.schema import App, AppEvent
from ...events.store import EventStore
from ...logging import get_logger
from ...timeutil import Clock
from ..base import Integration
from . import normalize as norm

log = get_logger("gcal")


class CalendarGoneError(Exception):
    """Raised to simulate a ``410 GONE`` that invalidates the stored sync token."""


class GCalSync(Integration):
    """Sync a Google Calendar into canonical events."""

    app = App.GCAL
    entity_types = ("event", "attendee")

    def __init__(
        self,
        store: EventStore,
        *,
        clock: Clock | None = None,
        fixtures: dict[str, Any] | None = None,
        fixtures_path: str | Path | None = None,
        service: Any | None = None,
    ) -> None:
        super().__init__(store, clock=clock, fixtures=fixtures)
        self._service = service
        if fixtures is None and service is None and fixtures_path is not None:
            self.fixtures = json.loads(Path(fixtures_path).read_text(encoding="utf-8"))

    @property
    def is_live(self) -> bool:
        return self._service is not None

    @property
    def calendar_id(self) -> str:
        data = self._load_meta()
        return data.get("calendar", {}).get("id", "primary")

    # -- sync -------------------------------------------------------------

    def sync(self, *, ingested_at: datetime) -> Iterator[AppEvent]:
        data = self._load_meta()
        calendar_id = data.get("calendar", {}).get("id", "primary")
        batches = data.get("sync_batches", [])

        last_token = self.store.get_cursor("gcal", calendar_id)
        start_index = self._resume_index(batches, last_token)

        for batch in batches[start_index:]:
            for event in batch.get("events", []):
                yield from self._emit_event(calendar_id, event, ingested_at)
            self.store.set_cursor("gcal", calendar_id, batch.get("sync_token"))

    def _resume_index(self, batches: list[dict[str, Any]], last_token: str | None) -> int:
        """Find the batch index to resume from given the last consumed token.

        If the token is not found among the batches it behaves like a ``410``: a
        full resync from the first batch. This mirrors clearing local state and
        starting over when the server reports the token is gone.
        """
        if last_token is None:
            return 0
        for i, batch in enumerate(batches):
            if batch.get("sync_token") == last_token:
                return i + 1
        log.info("sync token %s not found, performing full resync", last_token)
        return 0

    def _emit_event(
        self, calendar_id: str, event: dict[str, Any], ingested_at: datetime
    ) -> Iterator[AppEvent]:
        valid_at = norm.event_updated_at(event) or norm.event_start_at(event) or ingested_at
        if norm.is_cancelled(event):
            yield algebra.delete_entity(
                app="gcal", entity_type="event", entity_id=event["id"],
                valid_at=valid_at, ingested_at=ingested_at,
                provenance={"source": "calendar.events.list", "status": "cancelled"},
            )
            return

        normalized = norm.normalize_event(calendar_id, event)
        yield algebra.upsert_entity(
            app="gcal", entity_type="event", entity_id=event["id"], payload=normalized,
            valid_at=valid_at, ingested_at=ingested_at,
            parent_entity_ref=calendar_id,
            source_cursor=event.get("updated"),
            provenance={"source": "calendar.events.list"},
        )
        # Attendee responses as edges from the event so RSVP state is queryable.
        for attendee in normalized["attendees"]:
            email = attendee.get("email")
            if not email:
                continue
            yield algebra.upsert_edge(
                app="gcal", entity_type="event", entity_id=event["id"],
                edge_kind="attendee", edge_target=email,
                payload={"responseStatus": attendee.get("responseStatus")},
                valid_at=valid_at, ingested_at=ingested_at,
                provenance={"source": "calendar.events.attendees"},
            )

    def force_resync(self) -> None:
        """Clear the stored sync token, simulating recovery from a ``410 GONE``."""
        self.store.set_cursor("gcal", self.calendar_id, None)

    # -- data source ------------------------------------------------------

    def _load_meta(self) -> dict[str, Any]:
        if self._service is not None:
            return self._load_live()
        if self.fixtures is None:
            raise ValueError("GCalSync requires fixtures or a live service")
        return self.fixtures

    def _load_live(self) -> dict[str, Any]:  # pragma: no cover - requires network
        """Pull events via a live Calendar service, handling token expiry.

        Uses ``events().list`` with the stored ``syncToken``. On an ``HttpError`` with
        status 410 the token is cleared and a full sync is performed, per the
        documented reset behavior.
        """
        service = self._service
        calendar_id = "primary"
        token = self.store.get_cursor("gcal", calendar_id)
        events: list[dict[str, Any]] = []
        next_token = None
        try:
            request = service.events().list(calendarId=calendar_id, syncToken=token)
            while request is not None:
                response = request.execute()
                events.extend(response.get("items", []))
                next_token = response.get("nextSyncToken", next_token)
                request = service.events().list_next(request, response)
        except Exception as exc:  # pragma: no cover - network path
            if "410" in str(exc):
                self.force_resync()
                return self._load_live()
            raise
        return {
            "calendar": {"id": calendar_id},
            "sync_batches": [{"sync_token": next_token, "events": events}],
        }
