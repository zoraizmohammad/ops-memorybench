"""Slack payload normalization.

Maps raw Slack API shapes (users, channels, messages, reactions) into the
normalized entity payloads carried by canonical events. Keeping normalization
separate from sync means the same mapping serves both live ingestion and fixture
based ingestion, and makes the cross app vocabulary explicit.

Slack message timestamps (``ts``) are epoch seconds with a microsecond suffix and
also serve as a message's stable id within a channel, so they are used both for
``valid_at`` and as the entity id.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ...timeutil import from_epoch


def channel_id(channel: dict[str, Any]) -> str:
    return channel["id"]


def normalize_channel(channel: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Slack channel object."""
    return {
        "id": channel["id"],
        "name": channel.get("name"),
        "topic": channel.get("topic") if isinstance(channel.get("topic"), str)
        else (channel.get("topic", {}) or {}).get("value"),
        "is_private": bool(channel.get("is_private", False)),
    }


def normalize_user(user: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Slack user object."""
    return {
        "id": user["id"],
        "name": user.get("name"),
        "real_name": user.get("real_name"),
        "tz": user.get("tz"),
        "is_admin": bool(user.get("is_admin", False)),
    }


def message_id(channel: str, ts: str) -> str:
    """The stable id of a message is its channel and ts together."""
    return f"{channel}:{ts}"


def normalize_message(channel: str, message: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Slack message object."""
    return {
        "id": message_id(channel, message["ts"]),
        "channel": channel,
        "ts": message["ts"],
        "user": message.get("user"),
        "text": message.get("text", ""),
        "reactions": message.get("reactions", []),
    }


def channel_created_at(channel: dict[str, Any]) -> datetime:
    created = channel.get("created")
    return from_epoch(created) if created else from_epoch("0")


def user_valid_anchor(data: dict[str, Any]) -> datetime:
    """A stable valid time anchor for users, who lack a creation timestamp.

    Uses the earliest channel creation time in the workspace as a proxy for "has
    existed as long as we have observed this workspace". This is deterministic
    across syncs, so user event ids are stable and re sync is idempotent.
    """
    created = [c.get("created") for c in data.get("channels", []) if c.get("created")]
    if not created:
        return from_epoch("0")
    return from_epoch(min(created))


def message_ts(ts: str) -> datetime:
    return from_epoch(ts)
