"""Pluggable embeddings with a deterministic fallback.

Dense retrieval complements lexical retrieval by capturing semantic similarity. The
embedder is an interface so a real model (Anthropic, a sentence transformer, or a
hosted endpoint) can be swapped in. The default is a deterministic hashing embedder
that needs no model and no network, so the keyless path still has a meaningful dense
signal and is fully reproducible.

The hashing embedder maps tokens into a fixed dimensional vector via feature hashing
with sign, then L2 normalizes. It will not match a learned model's quality, but it
gives stable, non trivial similarity (shared tokens raise cosine similarity) which is
enough to demonstrate and test hybrid retrieval end to end without a dependency.
"""

from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod

from .bm25 import tokenize


class Embedder(ABC):
    """Interface for turning text into a dense vector."""

    dim: int

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal length vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class HashingEmbedder(Embedder):
    """A deterministic feature hashing embedder, no model required.

    Each token is hashed to a bucket and a sign; token contributions accumulate and
    the vector is L2 normalized. Bigrams are included so word order carries a little
    signal. Identical text always yields the identical vector.
    """

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _bucket_and_sign(self, token: str) -> tuple[int, float]:
        h = hashlib.sha1(token.encode("utf-8")).digest()
        bucket = int.from_bytes(h[:4], "big") % self.dim
        sign = 1.0 if (h[4] & 1) == 0 else -1.0
        return bucket, sign

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = tokenize(text)
        features = list(tokens)
        # Add bigrams for a little order sensitivity.
        features += [f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        for feat in features:
            bucket, sign = self._bucket_and_sign(feat)
            vec[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]


class AnthropicEmbedder(Embedder):  # pragma: no cover - requires network and key
    """Placeholder for a hosted embedding model.

    Anthropic does not currently expose a first party embeddings endpoint, so a
    production deployment would wire a sentence transformer or a hosted embeddings
    provider here behind this same interface. The hashing embedder is the default and
    keeps the platform fully functional without one.
    """

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim
        raise NotImplementedError(
            "Wire a real embeddings provider here. The HashingEmbedder is the "
            "keyless default and satisfies the retrieval interface."
        )

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


def default_embedder() -> Embedder:
    """Return the default embedder, the deterministic hashing embedder."""
    return HashingEmbedder()
