"""Google Docs and Drive sync adapter.

Ingests documents into canonical events by taking our own content snapshots. Each
document becomes an entity; each revision becomes an appended version whose payload
includes the exported markdown and its content hash. The revision's modified time is
the valid time, so reconstructing a document as of a past instant returns the
content that was actually current then, which the Docs API alone cannot do.

This is the documented correct approach for Docs replay: use Drive and Docs as
signals about what changed and when, and store self owned immutable content versions
in the history engine as the replay substrate.
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
from .export import export_revision


class GDocsSync(Integration):
    """Sync Google Docs documents into canonical content versioned events."""

    app = App.GDOCS
    entity_types = ("document",)

    def __init__(
        self,
        store: EventStore,
        *,
        clock: Clock | None = None,
        fixtures: dict[str, Any] | None = None,
        fixtures_path: str | Path | None = None,
        docs_service: Any | None = None,
        drive_service: Any | None = None,
    ) -> None:
        super().__init__(store, clock=clock, fixtures=fixtures)
        self._docs = docs_service
        self._drive = drive_service
        if fixtures is None and docs_service is None and fixtures_path is not None:
            self.fixtures = json.loads(Path(fixtures_path).read_text(encoding="utf-8"))

    @property
    def is_live(self) -> bool:
        return self._docs is not None or self._drive is not None

    # -- sync -------------------------------------------------------------

    def sync(self, *, ingested_at: datetime) -> Iterator[AppEvent]:
        data = self._load()
        for document in data.get("documents", []):
            meta = norm.document_metadata(document)
            revisions = document.get("revisions", [])
            first_modified = (
                norm.revision_modified_at(revisions[0]) if revisions else ingested_at
            )
            # The document entity carries metadata, valid as of its first revision.
            yield algebra.upsert_entity(
                app="gdocs", entity_type="document", entity_id=meta["id"], payload=meta,
                valid_at=first_modified or ingested_at, ingested_at=ingested_at,
                provenance={"source": "drive.files.get"},
            )
            # Each revision is an appended content version.
            for revision in revisions:
                modified = norm.revision_modified_at(revision) or ingested_at
                exported = export_revision(document, revision)
                yield algebra.append_version(
                    app="gdocs", entity_type="document", entity_id=meta["id"],
                    payload=exported, valid_at=modified, ingested_at=ingested_at,
                    source_cursor=revision.get("revision_id"),
                    provenance={
                        "source": "self_owned_export",
                        "revision_id": revision.get("revision_id"),
                    },
                )
        self.store.set_cursor("gdocs", "drive", data.get("drive", {}).get("id"))

    # -- data source ------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if self._docs is not None or self._drive is not None:
            return self._load_live()
        if self.fixtures is None:
            raise ValueError("GDocsSync requires fixtures or a live service")
        return self.fixtures

    def _load_live(self) -> dict[str, Any]:  # pragma: no cover - requires network
        """Pull documents and revisions via live Drive and Docs services.

        Lists document files from Drive, fetches each revision's metadata, exports
        the latest content to markdown via the Docs body, and content hashes it.
        Historical revision content is captured incrementally over time because the
        APIs do not offer arbitrary historical export; this is the documented
        limitation that motivates self owned snapshots.
        """
        drive = self._drive
        docs = self._docs
        files = (
            drive.files()
            .list(q="mimeType='application/vnd.google-apps.document'")
            .execute()
            .get("files", [])
        )
        documents: list[dict[str, Any]] = []
        for f in files:
            doc = docs.documents().get(documentId=f["id"]).execute()
            from .export import render_markdown_from_doc

            markdown = render_markdown_from_doc(doc)
            documents.append(
                {
                    "id": f["id"],
                    "name": f.get("name"),
                    "mimeType": f.get("mimeType"),
                    "owners": [o.get("emailAddress") for o in f.get("owners", [])],
                    "revisions": [
                        {
                            "revision_id": "latest",
                            "modified_time": f.get("modifiedTime"),
                            "exported_markdown": markdown,
                        }
                    ],
                }
            )
        return {"drive": {"id": "drive"}, "documents": documents}
