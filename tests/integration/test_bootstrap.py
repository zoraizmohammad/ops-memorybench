"""Tests for cold start bootstrapping and the memory graph."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ombench.events.store import EventStore
from ombench.integrations.gdocs.sync import GDocsSync
from ombench.integrations.slack.sync import SlackSync
from ombench.memory.bootstrap import ColdStartBootstrapper
from ombench.memory.graph import neighbors, proximity, subjects_index
from ombench.memory.resolver import resolve_pair
from ombench.memory.schema import MemoryItem, MemoryType, Namespace
from ombench.memory.store import MemoryStore
from ombench.storage import open_memory_store, open_store
from ombench.timeutil import UTC, FrozenClock

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def store(config):
    s = open_store(config)
    es = EventStore(s.backend, s.blobs)
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    SlackSync(es, clock=clock, fixtures_path=FIXTURES / "slack" / "workspace.json").run_sync()
    GDocsSync(es, clock=clock, fixtures_path=FIXTURES / "gdocs" / "docs.json").run_sync()
    yield s
    s.close()


def test_bootstrap_extracts_structured_facts(store, config):
    boot = ColdStartBootstrapper(store)
    result = boot.bootstrap(kb_root=config.kb_dir)
    assert result.structured_facts > 0
    assert result.total_promoted > 0
    # A user timezone fact should be present.
    items = boot.memory.all_items()
    claims = [i.claim for i in items]
    assert any("timezone" in c for c in claims)
    assert any("Channel" in c for c in claims)


def test_bootstrap_seeds_before_trajectories(store, config):
    boot = ColdStartBootstrapper(store)
    boot.bootstrap(kb_root=config.kb_dir)
    from ombench.memory.kb import KnowledgeBase

    kb = KnowledgeBase(config.kb_dir)
    text = kb.mounted_text().lower()
    # The knowledge base is useful with zero trajectories.
    assert "timezone" in text or "channel" in text


def test_bootstrap_document_owner(store, config):
    boot = ColdStartBootstrapper(store)
    boot.bootstrap(kb_root=config.kb_dir)
    claims = [i.claim for i in boot.memory.all_items()]
    assert any("owned by" in c for c in claims)


def _item(claim, subject="Alice"):
    return MemoryItem(type=MemoryType.SEMANTIC, namespace=Namespace.USER, subject=subject, claim=claim)


def test_graph_neighbors_and_proximity():
    s = open_memory_store()
    ms = MemoryStore(s)
    a = _item("Prefers mornings")
    b = _item("Prefers not mornings")
    ms.add(a)
    ms.add(b)
    resolve_pair(ms, a, b)
    # The winner supersedes the loser, so they are one hop apart.
    winner = a if a.confidence >= b.confidence else b
    loser = b if winner is a else a
    assert loser.memory_id in neighbors(ms, winner.memory_id)
    assert proximity(ms, winner.memory_id, loser.memory_id) > 0
    s.close()


def test_subjects_index():
    s = open_memory_store()
    ms = MemoryStore(s)
    ms.add(_item("Prefers afternoons", subject="Alice"))
    ms.add(_item("Likes concise updates", subject="Bob"))
    idx = subjects_index(ms)
    assert "user:Alice" in idx
    assert "user:Bob" in idx
    s.close()


def test_proximity_unreachable_is_zero():
    s = open_memory_store()
    ms = MemoryStore(s)
    a = _item("x", subject="A")
    b = _item("y", subject="B")
    ms.add(a)
    ms.add(b)
    assert proximity(ms, a.memory_id, b.memory_id) == 0.0
    s.close()
