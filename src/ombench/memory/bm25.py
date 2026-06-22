"""A small, dependency free BM25 lexical index.

Operational work often hinges on exact terms: channel names, dates, codes, person
names, and precise phrases that dense retrieval can blur. So lexical retrieval stays
in the loop alongside embeddings. This is a compact, well understood BM25
implementation over an in memory corpus, sufficient for the knowledge base scale and
fully deterministic.

BM25 scores a document for a query as the sum over query terms of the term's IDF
times a saturating term frequency factor controlled by ``k1`` and a length
normalization controlled by ``b``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@dataclass
class BM25Index:
    """An in memory BM25 index over string documents keyed by id."""

    k1: float = 1.5
    b: float = 0.75
    doc_ids: list[str] = field(default_factory=list)
    doc_tokens: dict[str, list[str]] = field(default_factory=dict)
    doc_freqs: dict[str, dict[str, int]] = field(default_factory=dict)
    df: dict[str, int] = field(default_factory=dict)
    doc_len: dict[str, int] = field(default_factory=dict)
    avg_len: float = 0.0

    def add(self, doc_id: str, text: str) -> None:
        """Add or replace a document in the index."""
        if doc_id in self.doc_tokens:
            self._remove(doc_id)
        tokens = tokenize(text)
        freqs: dict[str, int] = {}
        for tok in tokens:
            freqs[tok] = freqs.get(tok, 0) + 1
        self.doc_ids.append(doc_id)
        self.doc_tokens[doc_id] = tokens
        self.doc_freqs[doc_id] = freqs
        self.doc_len[doc_id] = len(tokens)
        for term in freqs:
            self.df[term] = self.df.get(term, 0) + 1
        self._recompute_avg()

    def _remove(self, doc_id: str) -> None:
        for term in self.doc_freqs.get(doc_id, {}):
            self.df[term] -= 1
            if self.df[term] <= 0:
                del self.df[term]
        self.doc_ids.remove(doc_id)
        del self.doc_tokens[doc_id]
        del self.doc_freqs[doc_id]
        del self.doc_len[doc_id]

    def _recompute_avg(self) -> None:
        self.avg_len = (
            sum(self.doc_len.values()) / len(self.doc_len) if self.doc_len else 0.0
        )

    @property
    def n_docs(self) -> int:
        return len(self.doc_ids)

    def _idf(self, term: str) -> float:
        n = self.n_docs
        df = self.df.get(term, 0)
        # The standard BM25 idf with a 0.5 smoothing, floored at zero.
        return max(0.0, math.log((n - df + 0.5) / (df + 0.5) + 1.0))

    def score(self, query: str, doc_id: str) -> float:
        """BM25 score of one document for a query."""
        freqs = self.doc_freqs.get(doc_id)
        if not freqs:
            return 0.0
        dl = self.doc_len[doc_id]
        score = 0.0
        for term in tokenize(query):
            if term not in freqs:
                continue
            tf = freqs[term]
            idf = self._idf(term)
            denom = tf + self.k1 * (1 - self.b + self.b * dl / (self.avg_len or 1.0))
            score += idf * (tf * (self.k1 + 1)) / (denom or 1.0)
        return score

    def search(self, query: str, *, top_k: int = 10) -> list[tuple[str, float]]:
        """Return the top scoring document ids and scores for a query."""
        scored = [(doc_id, self.score(query, doc_id)) for doc_id in self.doc_ids]
        scored = [(d, s) for d, s in scored if s > 0]
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:top_k]
