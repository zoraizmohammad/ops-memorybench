# Memory model

The knowledge base is a compiled, human readable filesystem of durable knowledge plus
a hybrid retrieval index over it. It is deliberately a filesystem and not only a
vector store, because a legible, auditable, diffable knowledge base is far more useful
during a demo and far easier to reason about than an opaque embedding blob.

## Taxonomy

Three classes, following the agent memory literature:

- **episodic**: specific past events, interactions, and outcomes
- **semantic**: stable facts, preferences, norms, contacts, project context
- **procedural**: reusable workflows, how we do things, approval chains, conventions

Each `MemoryItem` carries a namespace (`user`, `team`, `project`, `app_state`), an
explicit confidence, evidence references back to the trajectories or snapshots it was
derived from, a class specific TTL policy, and an ACL.

## Append only with explicit contradictions

The cardinal policy is that memory items are immutable. A claim is never overwritten in
place. When two items make competing claims about the same subject, the resolver
records a `supersedes` and `contradicts` edge and marks the losing item inactive,
choosing the active view by confidence then recency then ACL priority. Provenance is
always retained. This mirrors append only and bitemporal history design: actual
knowledge may be revised, but the record of what was believed is append only.

## The compile pipeline

```
trajectories + app state
        |
        v
candidate extractor   (explicit statements, corrections, repeated procedures, app norms)
        |
        v
scorer                (evidence based logistic confidence)
        |
        v
promotion threshold   (above ~0.42 are promoted)
        |
        v
append only store     (deduplicated by content hash)
        |
        v
contradiction resolver (supersedes / contradicts edges, active view)
        |
        v
KB filesystem          (markdown with frontmatter and json provenance)
```

## Retrieval

The runtime retriever is hybrid:

1. **route** the query to likely namespaces
2. **retrieve** lexical candidates with BM25 and semantic candidates with embeddings
3. **fuse** the two rankings with reciprocal rank fusion
4. **graph expand** one hop over supports and derived_from edges
5. **rerank** with normalized fusion plus namespace prior, confidence, and freshness,
   minus contradiction and privacy risk
6. **pack** a token budget bounded bundle, maximizing value per token

Lexical retrieval stays in the loop because operational work depends on exact names,
dates, codes, and phrases that dense retrieval blurs. Budget packing matters because
long context is not free: relevant information lost in a large context is used poorly,
so a tight high value bundle beats dumping the whole knowledge base.

## Forgetting

TTL is class specific, not one global expiry: explicit personal preferences never
expire automatically, team norms have a long TTL with reconfirmation, project facts
decay after archive, and transient cues are short lived. This keeps durable knowledge
where it matters and avoids polluting the mounted KB with stale noise.
