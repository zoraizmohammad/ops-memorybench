"""Tests for the memory store and contradiction resolver."""

from __future__ import annotations

from datetime import datetime

import pytest

from ombench.memory.resolver import contradicts, resolve_all, resolve_pair
from ombench.memory.schema import EdgeRelation, MemoryItem, MemoryType, Namespace
from ombench.memory.store import MemoryStore
from ombench.storage import open_memory_store
from ombench.timeutil import UTC


@pytest.fixture
def mstore():
    s = open_memory_store()
    yield MemoryStore(s)
    s.close()


def _item(claim, conf=0.5, day=1, subject="Alice", ns=Namespace.USER):
    return MemoryItem(
        type=MemoryType.SEMANTIC, namespace=ns, subject=subject, claim=claim,
        confidence=conf, valid_at=datetime(2026, 5, day, tzinfo=UTC),
        created_at=datetime(2026, 5, day, tzinfo=UTC),
    )


def test_add_is_idempotent(mstore):
    item = _item("Prefers afternoons")
    mstore.add(item)
    mstore.add(item)
    assert len(mstore.all_items()) == 1


def test_add_with_evidence_round_trip(mstore):
    from ombench.memory.schema import EvidenceRef

    item = MemoryItem(
        type=MemoryType.SEMANTIC, namespace=Namespace.USER, subject="Alice",
        claim="Prefers afternoons",
        evidence=[EvidenceRef(kind="trace", ref="trace_1")],
    )
    mstore.add(item)
    loaded = mstore.get(item.memory_id)
    assert loaded.evidence[0].ref == "trace_1"


def test_contradiction_detection():
    a = _item("Prefers morning meetings")
    b = _item("Prefers not morning meetings")
    assert contradicts(a, b)


def test_no_contradiction_different_subject():
    a = _item("Prefers mornings", subject="Alice")
    b = _item("Prefers not mornings", subject="Bob")
    assert not contradicts(a, b)


def test_no_contradiction_unrelated_topics():
    a = _item("Prefers afternoons")
    b = _item("Never uses Slack threads for launches")
    assert not contradicts(a, b)


def test_resolve_pair_higher_confidence_wins(mstore):
    a = _item("Prefers morning meetings", conf=0.4, day=1)
    b = _item("Prefers not morning meetings", conf=0.8, day=2)
    mstore.add(a)
    mstore.add(b)
    result = resolve_pair(mstore, a, b)
    assert result.active_id == b.memory_id
    assert a.memory_id in result.inactivated
    # b stays active, a inactivated.
    assert mstore.get(b.memory_id).active is True
    assert mstore.get(a.memory_id).active is False


def test_resolve_tie_breaks_to_recent(mstore):
    a = _item("Prefers morning meetings", conf=0.6, day=1)
    b = _item("Prefers not morning meetings", conf=0.6, day=5)
    mstore.add(a)
    mstore.add(b)
    result = resolve_pair(mstore, a, b)
    assert result.active_id == b.memory_id


def test_resolve_records_edges(mstore):
    a = _item("Prefers morning meetings", conf=0.8, day=2)
    b = _item("Prefers not morning meetings", conf=0.4, day=1)
    mstore.add(a)
    mstore.add(b)
    resolve_pair(mstore, a, b)
    edges = mstore.edges_from(a.memory_id)
    relations = {e["relation"] for e in edges}
    assert EdgeRelation.SUPERSEDES.value in relations


def test_resolve_all_scans_groups(mstore):
    mstore.add(_item("Prefers morning meetings", conf=0.4, day=1))
    mstore.add(_item("Prefers not morning meetings", conf=0.9, day=2))
    mstore.add(_item("Announces launches in announcements", conf=0.7, subject="team", ns=Namespace.TEAM))
    results = resolve_all(mstore)
    assert len(results) == 1
    # The unrelated team norm remains active.
    active = mstore.all_items(active_only=True)
    claims = {i.claim for i in active}
    assert "Announces launches in announcements" in claims


def test_provenance_retained_after_resolution(mstore):
    a = _item("Prefers morning meetings", conf=0.4, day=1)
    b = _item("Prefers not morning meetings", conf=0.9, day=2)
    mstore.add(a)
    mstore.add(b)
    resolve_pair(mstore, a, b)
    # The superseded item still exists, just inactive.
    assert mstore.get(a.memory_id) is not None
    assert len(mstore.all_items()) == 2
