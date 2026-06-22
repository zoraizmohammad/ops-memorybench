"""Hybrid memory retrieval.

The runtime interface the agent uses to pull a compact, relevant memory bundle for a
query. The pipeline follows the design:

1. route the query to likely namespaces
2. retrieve lexical candidates with BM25 and semantic candidates with embeddings
3. fuse the two rankings with reciprocal rank fusion
4. graph expand one hop over supports and derived_from edges
5. rerank with task aware features including the namespace prior, confidence, and
   freshness, minus contradiction and privacy risk
6. pack a budget bounded bundle, maximizing value per token

Keeping lexical retrieval in the loop matters because operational work depends on
exact names, dates, and codes that dense retrieval blurs. Packing to a budget matters
because long context is not free: relevant information lost in a large context is
used poorly, so a tight, high value bundle beats dumping the whole knowledge base.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..timeutil import utcnow
from .bm25 import BM25Index
from .embeddings import Embedder, cosine, default_embedder
from .router import route
from .schema import MemoryItem
from .store import MemoryStore

# Reranking weights, the Score(k | q, t) function from the design. Fusion dominates
# because lexical and dense relevance to the query is the primary signal; namespace
# prior, confidence, and freshness break ties and contradiction and privacy penalize.
_W = {
    "fusion": 1.5,
    "namespace": 0.5,
    "confidence": 0.4,
    "freshness": 0.2,
    "contradiction": 0.6,
    "privacy": 0.3,
}
# Approximate token cost per character, for budget packing.
_CHARS_PER_TOKEN = 4


@dataclass
class RetrievedMemory:
    """A retrieved item with its score and the reason it was retrieved."""

    item: MemoryItem
    score: float
    lexical_rank: int | None = None
    dense_rank: int | None = None
    via_graph: bool = False


@dataclass
class MemoryBundle:
    """The packed bundle mounted into the agent context."""

    items: list[RetrievedMemory] = field(default_factory=list)
    token_estimate: int = 0

    def memory_ids(self) -> list[str]:
        return [r.item.memory_id for r in self.items]

    def to_text(self) -> str:
        """Render the bundle as a compact readable block for the agent."""
        lines = ["# Relevant memory", ""]
        for r in self.items:
            lines.append(f"- ({r.item.type.value}) {r.item.claim}")
        return "\n".join(lines)


def reciprocal_rank_fusion(
    rankings: list[list[str]], *, k: int = 60
) -> dict[str, float]:
    """Fuse several ranked id lists into one score per id via RRF.

    RRF combines rankings without needing comparable raw scores: each list
    contributes ``1 / (k + rank)`` for the ids it ranks. It is the robust default for
    blending lexical and dense results.
    """
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return fused


class MemoryRetriever:
    """Hybrid retriever over the compiled memory store."""

    def __init__(self, store: MemoryStore, *, embedder: Embedder | None = None) -> None:
        self.store = store
        self.embedder = embedder or default_embedder()
        self.bm25 = BM25Index()
        self._vectors: dict[str, list[float]] = {}
        self._items: dict[str, MemoryItem] = {}
        self.reindex()

    def reindex(self) -> None:
        """Rebuild the lexical and dense indexes from active memory items."""
        self.bm25 = BM25Index()
        self._vectors = {}
        self._items = {}
        for item in self.store.all_items(active_only=True):
            text = self._index_text(item)
            self.bm25.add(item.memory_id, text)
            self._vectors[item.memory_id] = self.embedder.embed(text)
            self._items[item.memory_id] = item

    def _index_text(self, item: MemoryItem) -> str:
        return f"{item.subject or ''} {item.claim} {' '.join(item.tags)}"

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        candidate_k: int = 20,
        token_budget: int = 600,
        graph_expand: bool = True,
    ) -> MemoryBundle:
        """Retrieve and pack a memory bundle for a query."""
        if not self._items:
            return MemoryBundle()

        routes = route(query)

        # 1 and 2: lexical and dense candidate rankings.
        lexical = [doc for doc, _ in self.bm25.search(query, top_k=candidate_k)]
        qvec = self.embedder.embed(query)
        dense_scored = sorted(
            ((mid, cosine(qvec, vec)) for mid, vec in self._vectors.items()),
            key=lambda x: (-x[1], x[0]),
        )
        # Dense always contributes a full ranking; RRF uses rank, not raw score, so
        # weak similarity items still get placed and the reranker decides via the
        # namespace prior and confidence rather than being silently dropped.
        dense = [mid for mid, _ in dense_scored[:candidate_k]]

        lexical_rank = {mid: i for i, mid in enumerate(lexical)}
        dense_rank = {mid: i for i, mid in enumerate(dense)}

        # 3: fuse.
        fused = reciprocal_rank_fusion([lexical, dense])

        # 4: graph expand one hop.
        if graph_expand:
            for mid in list(fused.keys()):
                for edge in self.store.edges_from(mid):
                    if edge["relation"] in ("supports", "derived_from"):
                        fused.setdefault(edge["dst_id"], 0.0)
                        fused[edge["dst_id"]] += 0.5 / 60

        # 5: rerank with task aware features. Normalize fusion scores to 0..1 across
        # candidates first so the lexical and dense signal is comparable in
        # magnitude to the confidence and namespace terms rather than being dwarfed.
        max_fusion = max(fused.values()) if fused else 1.0
        ranked: list[RetrievedMemory] = []
        for mid, fusion_score in fused.items():
            item = self._items.get(mid)
            if item is None:
                continue
            norm_fusion = fusion_score / max_fusion if max_fusion else 0.0
            score = self._rerank_score(item, norm_fusion, routes)
            ranked.append(
                RetrievedMemory(
                    item=item, score=score,
                    lexical_rank=lexical_rank.get(mid),
                    dense_rank=dense_rank.get(mid),
                    via_graph=(mid not in lexical_rank and mid not in dense_rank),
                )
            )
        ranked.sort(key=lambda r: (-r.score, r.item.memory_id))

        # 6: pack to budget.
        return self._pack(ranked[: max(top_k, candidate_k)], top_k, token_budget)

    def _rerank_score(self, item: MemoryItem, fusion_score: float, routes) -> float:
        freshness = self._freshness(item)
        contradiction_risk = 0.0 if item.active else 1.0
        privacy_risk = 0.3 if item.acl == "personal" else 0.0
        return (
            _W["fusion"] * fusion_score
            + _W["namespace"] * routes.prior(item.namespace)
            + _W["confidence"] * item.confidence
            + _W["freshness"] * freshness
            - _W["contradiction"] * contradiction_risk
            - _W["privacy"] * privacy_risk
        )

    def _freshness(self, item: MemoryItem) -> float:
        ref = item.valid_at or item.created_at
        age_days = (utcnow() - ref).total_seconds() / 86400.0
        # Smoothly decays from 1 toward 0 over about a year. Clamped on both ends:
        # a future dated item (valid_at ahead of now, common for calendar events)
        # would otherwise score above 1.0 and over weight in the rerank.
        return max(0.0, min(1.0, 1.0 - age_days / 365.0))

    def _pack(self, ranked: list[RetrievedMemory], top_k: int, token_budget: int) -> MemoryBundle:
        bundle = MemoryBundle()
        for r in ranked:
            if len(bundle.items) >= top_k:
                break
            cost = max(1, len(r.item.claim) // _CHARS_PER_TOKEN)
            if bundle.token_estimate + cost > token_budget and bundle.items:
                continue
            bundle.items.append(r)
            bundle.token_estimate += cost
        return bundle
