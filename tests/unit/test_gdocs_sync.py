"""Tests for the Google Docs and Drive sync adapter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ombench.events.store import EventStore
from ombench.integrations.gdocs.export import export_revision, render_markdown_from_doc
from ombench.integrations.gdocs.sync import GDocsSync
from ombench.storage import open_memory_store
from ombench.timeutil import UTC, FrozenClock, from_iso

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "gdocs" / "docs.json"


@pytest.fixture
def store():
    s = open_memory_store()
    yield EventStore(s.backend, s.blobs)
    s.close()


@pytest.fixture
def synced(store):
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    GDocsSync(store, clock=clock, fixtures_path=FIXTURE).run_sync()
    return store


def test_export_revision_hashes_content():
    doc = {"id": "d1", "name": "Doc"}
    rev = {"revision_id": "r1", "exported_markdown": "# Title\n"}
    exported = export_revision(doc, rev)
    assert exported["markdown"] == "# Title\n"
    assert len(exported["content_hash"]) == 64


def test_documents_and_versions_ingested(synced):
    overview = synced.materialize_entity("gdocs", "document", "doc_redwood_overview")
    assert overview.version_count == 2
    # Latest version reflects the ready status and naming convention.
    assert "Status ready" in overview.payload["markdown"]
    assert "Naming convention" in overview.payload["markdown"]


def test_historical_content_time_travel(synced):
    # The key Docs replay capability: reconstruct content as of a past time.
    before_r2 = from_iso("2026-05-05T00:00:00Z")
    early = synced.materialize_entity(
        "gdocs", "document", "doc_redwood_overview", as_of_valid=before_r2
    )
    assert "Status draft" in early.payload["markdown"]
    assert "Naming convention" not in early.payload["markdown"]


def test_template_document_single_revision(synced):
    tmpl = synced.materialize_entity("gdocs", "document", "doc_meeting_notes_tmpl")
    assert tmpl.version_count == 1
    assert "## Decisions" in tmpl.payload["markdown"]


def test_content_addressing_stored_in_blobs(synced):
    # The exported content lives in the content addressed blob store.
    rows = list(synced.iter_events(app="gdocs", entity_id="doc_redwood_overview", load_payload=True))
    versions = [r for r in rows if r["op"] == "append_version"]
    assert len(versions) == 2
    for v in versions:
        assert "content_hash" in v["payload"]


def test_resync_idempotent(store):
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    sync = GDocsSync(store, clock=clock, fixtures_path=FIXTURE)
    sync.run_sync()
    count = store.count()
    second = sync.run_sync()
    assert second.events_new == 0
    assert store.count() == count


def test_render_markdown_from_doc():
    doc = {
        "body": {
            "content": [
                {"paragraph": {"paragraphStyle": {"namedStyleType": "TITLE"},
                               "elements": [{"textRun": {"content": "My Doc\n"}}]}},
                {"paragraph": {"paragraphStyle": {"namedStyleType": "HEADING_2"},
                               "elements": [{"textRun": {"content": "Section\n"}}]}},
                {"paragraph": {"paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                               "elements": [{"textRun": {"content": "Body text\n"}}]}},
            ]
        }
    }
    md = render_markdown_from_doc(doc)
    assert "# My Doc" in md
    assert "## Section" in md
    assert "Body text" in md
