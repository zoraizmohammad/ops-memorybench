"""Tests for the BM25 lexical index."""

from __future__ import annotations

from ombench.memory.bm25 import BM25Index, tokenize


def test_tokenize():
    assert tokenize("Hello, World! 123") == ["hello", "world", "123"]


def test_exact_term_match_ranks_first():
    idx = BM25Index()
    idx.add("d1", "announce launches in the announcements channel")
    idx.add("d2", "user prefers afternoon meetings")
    idx.add("d3", "the standup happens daily")
    results = idx.search("announcements channel")
    assert results[0][0] == "d1"


def test_no_match_returns_empty():
    idx = BM25Index()
    idx.add("d1", "calendar event")
    assert idx.search("nonexistent term xyz") == []


def test_rare_term_scores_higher_than_common():
    idx = BM25Index()
    idx.add("d1", "the the the redwood")
    idx.add("d2", "the the the the")
    idx.add("d3", "the the the the")
    # "redwood" is rare, so a query for it strongly favors d1.
    results = idx.search("redwood")
    assert results[0][0] == "d1"


def test_add_replaces_existing():
    idx = BM25Index()
    idx.add("d1", "original text")
    idx.add("d1", "replacement content")
    assert idx.n_docs == 1
    results = idx.search("replacement")
    assert results and results[0][0] == "d1"


def test_top_k_limits_results():
    idx = BM25Index()
    for i in range(10):
        idx.add(f"d{i}", "common term here")
    results = idx.search("common", top_k=3)
    assert len(results) == 3


def test_deterministic_tie_break():
    idx = BM25Index()
    idx.add("b", "term")
    idx.add("a", "term")
    results = idx.search("term")
    # Equal scores break ties by id ascending.
    assert [r[0] for r in results] == ["a", "b"]
