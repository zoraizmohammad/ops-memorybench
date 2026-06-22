"""Tests for the memory item schema and knowledge base filesystem."""

from __future__ import annotations

import pytest

from ombench.memory.kb import (
    KnowledgeBase,
    parse_markdown,
    render_markdown,
)
from ombench.memory.schema import (
    EvidenceRef,
    MemoryItem,
    MemoryType,
    Namespace,
    TTLPolicy,
)


def test_memory_id_derived_from_dedupe_key():
    a = MemoryItem(type=MemoryType.SEMANTIC, namespace=Namespace.USER,
                   subject="Alice", claim="Prefers afternoons")
    b = MemoryItem(type=MemoryType.SEMANTIC, namespace=Namespace.USER,
                   subject="alice", claim="prefers afternoons")
    # Case insensitive dedupe means these collapse to the same id.
    assert a.memory_id == b.memory_id


def test_distinct_claims_distinct_ids():
    a = MemoryItem(type=MemoryType.SEMANTIC, namespace=Namespace.USER,
                   subject="Alice", claim="Prefers afternoons")
    b = MemoryItem(type=MemoryType.SEMANTIC, namespace=Namespace.USER,
                   subject="Alice", claim="Avoids Fridays")
    assert a.memory_id != b.memory_id


def test_memory_item_is_frozen():
    from pydantic import ValidationError

    item = MemoryItem(type=MemoryType.SEMANTIC, namespace=Namespace.USER, claim="x")
    with pytest.raises(ValidationError):
        item.claim = "y"  # type: ignore[misc]


def test_frontmatter_round_trip():
    fm = {"title": "Alice", "tags": ["preference"], "confidence": 0.9}
    body = "## Facts\n\nPrefers afternoons."
    text = render_markdown(fm, body)
    parsed = parse_markdown(text)
    assert parsed.frontmatter == fm
    assert "Prefers afternoons" in parsed.body


def test_parse_markdown_without_frontmatter():
    doc = parse_markdown("just body text")
    assert doc.frontmatter == {}
    assert doc.body == "just body text"


def test_kb_path_routing(tmp_path):
    kb = KnowledgeBase(tmp_path)
    assert kb.path_for_subject(Namespace.USER, "Alice Aaronson").name == "alice-aaronson.md"
    assert kb.path_for_subject(Namespace.USER, "Alice").parent.name == "people"
    assert kb.path_for_subject(Namespace.TEAM, "exec comms").parent.name == "norms"
    proj = kb.path_for_subject(Namespace.PROJECT, "Launch Redwood")
    assert proj.parent.name == "launch-redwood"
    assert proj.parent.parent.name == "projects"


def test_write_and_read_document(tmp_path):
    kb = KnowledgeBase(tmp_path)
    kb.ensure_layout()
    path = kb.path_for_subject(Namespace.USER, "Alice")
    kb.write_document(path, {"title": "Alice"}, "## Facts\n\nPrefers afternoons.")
    doc = kb.read_document(path)
    assert doc.frontmatter["title"] == "Alice"
    assert "afternoons" in doc.body


def test_provenance_round_trip(tmp_path):
    kb = KnowledgeBase(tmp_path)
    kb.ensure_layout()
    item = MemoryItem(
        type=MemoryType.SEMANTIC, namespace=Namespace.USER, subject="Alice",
        claim="Prefers afternoons", confidence=0.9, ttl_policy=TTLPolicy.NEVER,
        evidence=[EvidenceRef(kind="trace", ref="trace_1", note="user said so")],
    )
    kb.write_provenance(item)
    prov = kb.read_provenance(item.memory_id)
    assert prov["claim"] == "Prefers afternoons"
    assert prov["evidence"][0]["ref"] == "trace_1"


def test_mounted_text_concatenates(tmp_path):
    kb = KnowledgeBase(tmp_path)
    kb.ensure_layout()
    kb.write_document(kb.path_for_subject(Namespace.USER, "Alice"), {"title": "Alice"}, "Prefers afternoons")
    kb.write_document(kb.path_for_subject(Namespace.TEAM, "norms"), {"title": "Norms"}, "Announce in announcements")
    text = kb.mounted_text()
    assert "afternoons" in text
    assert "announcements" in text
    assert "# file" in text


def test_iter_documents(tmp_path):
    kb = KnowledgeBase(tmp_path)
    kb.ensure_layout()
    kb.write_document(kb.path_for_subject(Namespace.USER, "Alice"), {}, "a")
    kb.write_document(kb.path_for_subject(Namespace.USER, "Bob"), {}, "b")
    assert len(kb.iter_documents()) == 2
