"""Slack sync adapter.

Ingests a Slack workspace into the canonical event log. The adapter honors the real
Slack acquisition model documented by Slack: near real time events arrive one per
request with a globally unique id, and historical backfill comes from
``conversations.history`` scoped by membership. Here both paths funnel into the same
normalized events.

By default the adapter reads a synthetic workspace fixture so the whole loop runs
keyless and PII free. When a live client is supplied (a ``slack_sdk`` WebClient or
any object exposing the same methods) it reads from the real API instead. The
emitted events are identical in either case, which is the point of the universal
format.

Slack specifics modeled here:

- channels become entities; channel membership becomes ``member`` edges
- users become entities
- messages become entities keyed by channel and ts
- message edits become appended versions, preserving history
- reactions become reaction events
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
from ...timeutil import Clock
from ..base import Integration
from . import normalize as norm


class SlackSync(Integration):
    """Sync a Slack workspace into canonical events."""

    app = App.SLACK
    entity_types = ("user", "channel", "message")

    def __init__(
        self,
        store: EventStore,
        *,
        clock: Clock | None = None,
        fixtures: dict[str, Any] | None = None,
        fixtures_path: str | Path | None = None,
        client: Any | None = None,
    ) -> None:
        super().__init__(store, clock=clock, fixtures=fixtures)
        self._client = client
        if fixtures is None and client is None and fixtures_path is not None:
            self.fixtures = json.loads(Path(fixtures_path).read_text(encoding="utf-8"))

    @property
    def is_live(self) -> bool:
        return self._client is not None

    # -- sync -------------------------------------------------------------

    def sync(self, *, ingested_at: datetime) -> Iterator[AppEvent]:
        data = self._load()
        # Users first so message authors resolve.
        for user in data.get("users", []):
            nu = norm.normalize_user(user)
            yield algebra.upsert_entity(
                app="slack", entity_type="user", entity_id=nu["id"], payload=nu,
                valid_at=ingested_at, ingested_at=ingested_at,
                provenance={"source": "slack.users.list"},
            )

        edits_by_msg = self._index_edits(data.get("edits", []))

        for channel in data.get("channels", []):
            nc = norm.normalize_channel(channel)
            created = norm.channel_created_at(channel)
            yield algebra.upsert_entity(
                app="slack", entity_type="channel", entity_id=nc["id"], payload=nc,
                valid_at=created, ingested_at=ingested_at,
                provenance={"source": "slack.conversations.list"},
            )
            # Membership edges, valid as of channel creation in the fixture model.
            for member in channel.get("members", []):
                yield algebra.upsert_edge(
                    app="slack", entity_type="channel", entity_id=nc["id"],
                    edge_kind="member", edge_target=member,
                    valid_at=created, ingested_at=ingested_at,
                    provenance={"source": "slack.conversations.members"},
                )

            for message in data.get("messages", {}).get(nc["id"], []):
                yield from self._emit_message(nc["id"], message, edits_by_msg, ingested_at)

        # Persist a coarse cursor marking the last sync. Live incremental sync would
        # store per channel oldest or latest ts here.
        self.store.set_cursor("slack", "workspace", data.get("team", {}).get("id"))

    def _emit_message(
        self,
        channel_id: str,
        message: dict[str, Any],
        edits_by_msg: dict[str, list[dict[str, Any]]],
        ingested_at: datetime,
    ) -> Iterator[AppEvent]:
        nm = norm.normalize_message(channel_id, message)
        ts = norm.message_ts(message["ts"])
        yield algebra.upsert_entity(
            app="slack", entity_type="message", entity_id=nm["id"], payload=nm,
            valid_at=ts, ingested_at=ingested_at, actor_ref=message.get("user"),
            parent_entity_ref=channel_id,
            source_cursor=message["ts"],
            provenance={"source": "slack.conversations.history"},
        )
        # Reactions as their own events so they can be time ordered.
        for reaction in message.get("reactions", []):
            yield algebra.status_change(
                app="slack", entity_type="message", entity_id=nm["id"],
                payload={"reaction": reaction.get("name"), "users": reaction.get("users", [])},
                valid_at=ts, ingested_at=ingested_at,
                provenance={"source": "slack.reactions"},
            )
        # Edits become appended versions at the edit time.
        for edit in edits_by_msg.get(nm["id"], []):
            edit_ts = norm.message_ts(edit["edited_ts"])
            edited_payload = dict(nm)
            edited_payload["text"] = edit["text"]
            yield algebra.append_version(
                app="slack", entity_type="message", entity_id=nm["id"],
                payload=edited_payload, valid_at=edit_ts, ingested_at=ingested_at,
                provenance={"source": "slack.message_changed"},
            )

    def _index_edits(self, edits: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        index: dict[str, list[dict[str, Any]]] = {}
        for edit in edits:
            mid = norm.message_id(edit["channel"], edit["ts"])
            index.setdefault(mid, []).append(edit)
        return index

    # -- data source ------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if self._client is not None:
            return self._load_live()
        if self.fixtures is None:
            raise ValueError("SlackSync requires fixtures or a live client")
        return self.fixtures

    def _load_live(self) -> dict[str, Any]:  # pragma: no cover - requires network
        """Pull a workspace via a live Slack client.

        Uses the documented methods: ``users_list``, ``conversations_list``,
        ``conversations_members``, and ``conversations_history``. This path runs only
        when a real client is injected and is exercised in live integration tests.
        """
        client = self._client
        users = client.users_list()["members"]
        channels = client.conversations_list(types="public_channel,private_channel")["channels"]
        messages: dict[str, list[dict[str, Any]]] = {}
        for ch in channels:
            ch["members"] = client.conversations_members(channel=ch["id"]).get("members", [])
            history = client.conversations_history(channel=ch["id"]).get("messages", [])
            messages[ch["id"]] = history
        return {"users": users, "channels": channels, "messages": messages, "edits": []}
