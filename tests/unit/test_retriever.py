"""Tests for the hybrid retriever and router."""

from __future__ import annotations

from datetime import datetime

import pytest

from ombench.memory.retriever import MemoryRetriever, reciprocal_rank_fusion
from ombench.memory.router import route
from ombench.memory.schema import MemoryItem, MemoryType, Namespace
from ombench.memory.store import MemoryStore
from ombench.storage import open_memory_store
from ombench.timeutil import UTC


@pytest.fixture
def retriever():
    s = open_memory_store()
    ms = MemoryStore(s)
    items = [
        MemoryItem(type=MemoryType.SEMANTIC, namespace=Namespace.USER, subject="user",
                   claim="Prefers afternoon meetings and avoids Fridays", confidence=0.9,
                   valid_at=datetime(2026, 5, 1, tzinfo=UTC)),
        MemoryItem(type=MemoryType.SEMANTIC, namespace=Namespace.TEAM, subject="team-norms",
                   claim="Announce launches in the announcements channel", confidence=0.8,
                   valid_at=datetime(2026, 5, 1, tzinfo=UTC)),
        MemoryItem(type=MemoryType.PROCEDURAL, namespace=Namespace.TEAM, subject="team-norms",
                   claim="Tag the approver before publishing a launch", confidence=0.75,
                   valid_at=datetime(2026, 5, 1, tzinfo=UTC)),
        MemoryItem(type=MemoryType.SEMANTIC, namespace=Namespace.PROJECT, subject="redwood",
                   claim="Customer docs are named Customer Name and date", confidence=0.7,
                   valid_at=datetime(2026, 5, 1, tzinfo=UTC)),
    ]
    for item in items:
        ms.add(item)
    yield MemoryRetriever(ms)
    s.close()


def test_route_user_query():
    scores = route("when do I prefer my meetings")
    assert scores.top(1)[0] == Namespace.USER


def test_route_team_query():
    scores = route("what is our announcement convention")
    assert Namespace.TEAM in scores.top(2)


def test_rrf_combines_rankings():
    # b is ranked first in one list and second in the other; a is third and first.
    # b accumulates the most reciprocal rank, so it tops the fused scores.
    fused = reciprocal_rank_fusion([["b", "c", "a"], ["b", "a", "d"]])
    top = max(fused.items(), key=lambda x: x[1])[0]
    assert top == "b"


def test_rrf_rewards_consistent_high_rank():
    fused = reciprocal_rank_fusion([["x", "y", "z"], ["x", "y", "z"]])
    # x ranked first in both beats y ranked second in both.
    assert fused["x"] > fused["y"] > fused["z"]


def test_retrieve_finds_relevant_preference(retriever):
    bundle = retriever.retrieve("reschedule my 1:1, what time do I like")
    claims = [r.item.claim for r in bundle.items]
    assert any("afternoon" in c.lower() for c in claims)


def test_retrieve_finds_announcement_norm(retriever):
    bundle = retriever.retrieve("where should I announce the launch")
    claims = [r.item.claim.lower() for r in bundle.items]
    assert any("announcements channel" in c for c in claims)


def test_retrieve_respects_top_k(retriever):
    bundle = retriever.retrieve("launch announcement approver", top_k=2)
    assert len(bundle.items) <= 2


def test_retrieve_respects_token_budget(retriever):
    bundle = retriever.retrieve("launch announcement approver convention", top_k=10, token_budget=5)
    # With a tiny budget only one item fits.
    assert len(bundle.items) == 1


def test_bundle_to_text(retriever):
    bundle = retriever.retrieve("afternoon meetings")
    text = bundle.to_text()
    assert "Relevant memory" in text


def test_empty_store_returns_empty_bundle():
    s = open_memory_store()
    r = MemoryRetriever(MemoryStore(s))
    assert r.retrieve("anything").items == []
    s.close()


def test_exact_term_beats_semantic(retriever):
    # An exact phrase query should surface the precisely matching item first.
    bundle = retriever.retrieve("announcements channel", top_k=1)
    assert "announcements channel" in bundle.items[0].item.claim.lower()
