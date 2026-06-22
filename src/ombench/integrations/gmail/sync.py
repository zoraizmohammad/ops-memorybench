"""Gmail sync adapter (future path).

Gmail is not required for the proof of concept, but it fits the same bitemporal
substrate cleanly, so this module sketches the integration to the same contract as
the others. The documented Gmail synchronization model is:

- perform a full sync once and store the most recent ``historyId``
- on subsequent syncs call ``users.history.list`` with ``startHistoryId`` to receive
  incremental changes (messages added, deleted, labels changed)
- if the stored ``historyId`` is too old the server signals it and a full sync is
  required, exactly analogous to the Calendar ``410`` reset

The mapping into canonical events is straightforward: a thread is an entity, a
message is an entity parented to its thread, a label change is a status change, and
a message deletion is a delete event. The valid time is the message internal date;
the ingest time is the sync time. This file implements the fixture path and the
event mapping so the design is concrete and testable, and documents the live path.

See ``docs/integrations-gmail.md`` for the full design.
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
from ...timeutil import Clock, from_epoch
from ..base import Integration


class GmailSync(Integration):
    """Sync Gmail messages into canonical events. Future path, fixture backed."""

    app = App.GMAIL
    entity_types = ("thread", "message")

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

    def sync(self, *, ingested_at: datetime) -> Iterator[AppEvent]:
        data = self._load()
        for message in data.get("messages", []):
            valid_at = from_epoch(int(message["internalDate"]) / 1000) if message.get(
                "internalDate"
            ) else ingested_at
            thread_id = message.get("threadId", message["id"])
            yield algebra.upsert_entity(
                app="gmail", entity_type="message", entity_id=message["id"],
                payload={
                    "id": message["id"],
                    "threadId": thread_id,
                    "from": message.get("from"),
                    "to": message.get("to"),
                    "subject": message.get("subject"),
                    "snippet": message.get("snippet"),
                    "labelIds": message.get("labelIds", []),
                },
                valid_at=valid_at, ingested_at=ingested_at,
                parent_entity_ref=thread_id,
                provenance={"source": "gmail.users.messages.get"},
            )
        self.store.set_cursor("gmail", "mailbox", str(data.get("historyId")))

    def _load(self) -> dict[str, Any]:
        if self._service is not None:  # pragma: no cover - requires network
            raise NotImplementedError(
                "Live Gmail sync is documented in docs/integrations-gmail.md and "
                "follows the historyId incremental model. Not enabled for the POC."
            )
        if self.fixtures is None:
            raise ValueError("GmailSync requires fixtures or a live service")
        return self.fixtures
