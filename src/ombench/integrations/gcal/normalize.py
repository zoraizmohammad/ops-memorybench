"""Google Calendar payload normalization.

Maps Calendar event resources into normalized payloads. Calendar represents a
deleted or cancelled event with ``status == "cancelled"`` in an incremental sync
response; the sync adapter turns those into delete events rather than dropping them,
because the API forbids hiding deletions when using a ``syncToken`` and a faithful
history must keep them.

Event start and end may be a ``dateTime`` (timed) or a ``date`` (all day). The
normalizer captures both and derives a single ``start_at`` used as the event's
valid time anchor.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ...timeutil import ensure_utc, from_iso


def is_cancelled(event: dict[str, Any]) -> bool:
    return event.get("status") == "cancelled"


def _time_field(field: dict[str, Any] | None) -> str | None:
    if not field:
        return None
    return field.get("dateTime") or field.get("date")


def event_start_at(event: dict[str, Any]) -> datetime | None:
    raw = _time_field(event.get("start"))
    if not raw:
        return None
    try:
        return from_iso(raw)
    except ValueError:
        # All day dates lack a time; treat midnight UTC.
        try:
            return ensure_utc(datetime.fromisoformat(raw))
        except ValueError:
            return None


def event_updated_at(event: dict[str, Any]) -> datetime | None:
    raw = event.get("updated")
    return from_iso(raw) if raw else None


def normalize_event(calendar_id: str, event: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Calendar event resource into a canonical payload."""
    return {
        "id": event["id"],
        "calendar_id": calendar_id,
        "summary": event.get("summary"),
        "status": event.get("status"),
        "start": _time_field(event.get("start")),
        "end": _time_field(event.get("end")),
        "recurrence": event.get("recurrence", []),
        "attendees": [
            {"email": a.get("email"), "responseStatus": a.get("responseStatus")}
            for a in event.get("attendees", [])
        ],
    }
