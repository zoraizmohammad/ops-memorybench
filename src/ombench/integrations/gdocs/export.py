"""Google Docs content export and snapshotting.

This is the crux of faithful Docs replay. The Docs API ``documents.get`` returns the
latest version of a document, not an arbitrary historical version, and Drive
revision metadata is not a full time travel document API. So the correct engineering
choice is to take our own immutable content snapshots at sync time and store those
content addressed versions in our own history engine. Drive and Docs are used as
signals about what changed and when; the replay substrate is our own object store.

This module produces the export payload for one document revision. In the fixture
path the markdown is already provided. In the live path it would call the Docs or
Drive export endpoint to render markdown or structured blocks and hash the result.
"""

from __future__ import annotations

from typing import Any

from ...ids import content_hash


def export_revision(document: dict[str, Any], revision: dict[str, Any]) -> dict[str, Any]:
    """Build the normalized, content addressed export of one document revision.

    The returned payload carries the markdown content and a content hash so that
    identical content across revisions deduplicates and any later integrity check
    can verify the snapshot.
    """
    markdown = revision.get("exported_markdown", "")
    return {
        "id": document["id"],
        "name": document.get("name"),
        "revision_id": revision.get("revision_id"),
        "mime_type": document.get("mimeType"),
        "owners": document.get("owners", []),
        "markdown": markdown,
        "content_hash": content_hash(markdown),
    }


def render_markdown_from_doc(doc_json: dict[str, Any]) -> str:  # pragma: no cover - live aid
    """Render markdown from a Docs ``documents.get`` body.

    A minimal renderer over the Docs structural elements, used on the live path
    where the API returns structured content rather than markdown. Handles
    paragraphs and heading named styles, which is enough for the operational
    documents this project targets.
    """
    body = doc_json.get("body", {})
    lines: list[str] = []
    for element in body.get("content", []):
        para = element.get("paragraph")
        if not para:
            continue
        style = para.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
        text = "".join(
            run.get("textRun", {}).get("content", "")
            for run in para.get("elements", [])
        ).rstrip("\n")
        if not text:
            continue
        if style.startswith("HEADING_"):
            level = int(style.split("_")[1]) if style.split("_")[1].isdigit() else 1
            lines.append("#" * level + " " + text)
        elif style == "TITLE":
            lines.append("# " + text)
        else:
            lines.append(text)
    return "\n\n".join(lines) + "\n"
