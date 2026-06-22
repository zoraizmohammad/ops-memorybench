"""Google Docs and Drive normalization helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ...timeutil import from_iso


def revision_modified_at(revision: dict[str, Any]) -> datetime | None:
    raw = revision.get("modified_time")
    return from_iso(raw) if raw else None


def document_metadata(document: dict[str, Any]) -> dict[str, Any]:
    """Normalize document level metadata, excluding content."""
    return {
        "id": document["id"],
        "name": document.get("name"),
        "mime_type": document.get("mimeType"),
        "owners": document.get("owners", []),
    }
