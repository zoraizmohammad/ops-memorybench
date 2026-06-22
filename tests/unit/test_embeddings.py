"""Tests for the embeddings layer."""

from __future__ import annotations

from ombench.memory.embeddings import HashingEmbedder, cosine, default_embedder


def test_embedding_is_deterministic():
    e = HashingEmbedder()
    assert e.embed("user prefers afternoons") == e.embed("user prefers afternoons")


def test_embedding_is_normalized():
    e = HashingEmbedder()
    vec = e.embed("some text here")
    norm = sum(v * v for v in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_dimension():
    e = HashingEmbedder(dim=128)
    assert len(e.embed("text")) == 128


def test_shared_tokens_raise_similarity():
    e = HashingEmbedder()
    a = e.embed("user prefers afternoon meetings")
    b = e.embed("user prefers afternoon calls")
    c = e.embed("completely different unrelated topic xyz")
    assert cosine(a, b) > cosine(a, c)


def test_cosine_identical_is_one():
    e = HashingEmbedder()
    v = e.embed("identical")
    assert abs(cosine(v, v) - 1.0) < 1e-6


def test_cosine_empty_is_zero():
    assert cosine([], []) == 0.0
    assert cosine([1, 2], [1, 2, 3]) == 0.0


def test_embed_many():
    e = HashingEmbedder()
    vecs = e.embed_many(["a", "b", "c"])
    assert len(vecs) == 3


def test_default_embedder():
    assert isinstance(default_embedder(), HashingEmbedder)


def test_empty_text_returns_zero_vector():
    e = HashingEmbedder(dim=16)
    vec = e.embed("")
    assert vec == [0.0] * 16
