"""The knowledge base compiler.

Ties the memory pipeline into one operation: take trajectories and app state, extract
candidates, score them into confidence, deduplicate and persist them append only,
resolve contradictions, then write the agent readable knowledge base filesystem with
provenance. This is the pipeline that turns history into a knowledge base the agent
reads at runtime to do tasks better.

The compiler is deterministic on the keyless path so a recompile from the same inputs
produces the same knowledge base, which the backtest depends on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..events.store import EventStore
from ..storage import Store
from ..timeutil import to_iso
from ..traces.schema import TraceRun
from .candidate_extractor import (
    ExtractedCandidate,
    extract_from_app_state,
    extract_from_trajectory,
    extract_repeated_procedures,
)
from .kb import TYPE_SECTION, KnowledgeBase
from .resolver import resolve_all
from .schema import (
    EvidenceRef,
    MemoryItem,
    MemoryType,
    Namespace,
    TTLPolicy,
)
from .scorer import score_candidate
from .store import MemoryStore

# Minimum confidence for a candidate to be promoted into the knowledge base. Set
# just below the confidence of an app state convention from a team's own canonical
# documents, so cold start bootstrapping works while lone uncertain extractions with
# contradictions stay out.
PROMOTION_THRESHOLD = 0.42

# TTL policy by memory type and namespace, per the forgetting design.
_TTL_BY_TYPE = {
    MemoryType.PROCEDURAL: TTLPolicy.LONG,
    MemoryType.SEMANTIC: TTLPolicy.MEDIUM,
    MemoryType.EPISODIC: TTLPolicy.SHORT,
}


@dataclass
class CompileResult:
    """Summary of a compile run."""

    candidates: int = 0
    promoted: int = 0
    contradictions_resolved: int = 0
    files_written: list[str] = field(default_factory=list)


class KnowledgeCompiler:
    """Compiles trajectories and app state into the knowledge base."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.events = EventStore(store.backend, store.blobs)
        self.memory = MemoryStore(store)

    def compile(
        self,
        *,
        runs: list[TraceRun] | None = None,
        include_app_state: bool = True,
        kb_root=None,
        write_files: bool = True,
    ) -> CompileResult:
        """Run the full compile pipeline and optionally write the KB filesystem."""
        runs = runs or []
        result = CompileResult()

        candidates: list[ExtractedCandidate] = []
        for run in runs:
            candidates.extend(extract_from_trajectory(run))
        candidates.extend(extract_repeated_procedures(runs))
        if include_app_state:
            candidates.extend(extract_from_app_state(self.events))
        result.candidates = len(candidates)

        # Count corroboration: how many candidates share a normalized claim, which
        # raises confidence for repeated independent observations.
        corroboration = self._corroboration_counts(candidates)

        for cand in candidates:
            key = self._claim_key(cand)
            conf = score_candidate(
                cand, corroborating_sources=max(0, corroboration.get(key, 1) - 1)
            )
            if conf < PROMOTION_THRESHOLD:
                continue
            item = self._to_item(cand, conf)
            self.memory.add(item)
            result.promoted += 1

        resolutions = resolve_all(self.memory)
        result.contradictions_resolved = len(resolutions)

        if write_files and kb_root is not None:
            result.files_written = self._write_kb(kb_root)

        return result

    # -- helpers ----------------------------------------------------------

    def _claim_key(self, cand: ExtractedCandidate) -> str:
        c = cand.candidate
        return f"{c.kind}|{c.namespace}|{c.text.strip().lower()}"

    def _corroboration_counts(self, candidates: list[ExtractedCandidate]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for cand in candidates:
            counts[self._claim_key(cand)] = counts.get(self._claim_key(cand), 0) + 1
        return counts

    def _to_item(self, cand: ExtractedCandidate, confidence: float) -> MemoryItem:
        c = cand.candidate
        mtype = MemoryType(c.kind)
        namespace = Namespace(c.namespace)
        acl = {"user": "personal", "team": "team", "project": "project"}.get(c.namespace, "team")
        evidence = [
            EvidenceRef(kind=cand.evidence_type, ref=ref, note=cand.source_kind)
            for ref in cand.evidence_ref.split(",")
        ]
        return MemoryItem(
            type=mtype,
            namespace=namespace,
            subject=c.subject or self._infer_subject(cand),
            claim=c.text.strip(),
            confidence=confidence,
            ttl_policy=_TTL_BY_TYPE.get(mtype, TTLPolicy.MEDIUM),
            acl=acl,
            evidence=evidence,
            tags=[cand.source_kind],
        )

    def _infer_subject(self, cand: ExtractedCandidate) -> str:
        """Pick a reasonable subject when the candidate did not name one."""
        ns = cand.candidate.namespace
        if ns == "user":
            return "user"
        if ns == "team":
            return "team-norms"
        if ns == "project":
            return cand.extra.get("entity_type", "project")
        return "general"

    def _write_kb(self, kb_root) -> list[str]:
        """Write active memory items into the readable knowledge base filesystem."""
        kb = KnowledgeBase(kb_root)
        kb.ensure_layout()
        items = self.memory.all_items(active_only=True)

        # Group items by their destination file.
        by_path: dict = {}
        for item in items:
            path = kb.path_for_subject(item.namespace, item.subject or "general")
            by_path.setdefault(path, []).append(item)
            kb.write_provenance(item)

        written: list[str] = []
        for path, group in by_path.items():
            frontmatter = {
                "subject": group[0].subject,
                "namespace": group[0].namespace.value,
                "item_count": len(group),
                "compiled_at": to_iso(group[0].created_at),
            }
            body = self._render_body(group)
            kb.write_document(path, frontmatter, body)
            written.append(str(path.relative_to(kb.root)))
        return sorted(written)

    def _render_body(self, items: list[MemoryItem]) -> str:
        """Render a group of items into readable markdown with sections by type."""
        title = items[0].subject or "Knowledge"
        lines = [f"# {title}", ""]
        for mtype in (MemoryType.SEMANTIC, MemoryType.PROCEDURAL, MemoryType.EPISODIC):
            group = [i for i in items if i.type == mtype]
            if not group:
                continue
            lines.append(f"## {TYPE_SECTION[mtype]}")
            lines.append("")
            for item in sorted(group, key=lambda i: -i.confidence):
                conf = f"{item.confidence:.2f}"
                ev = ", ".join(e.ref for e in item.evidence) or "n/a"
                lines.append(f"- {item.claim}")
                lines.append(f"  - confidence {conf} memory_id {item.memory_id} evidence {ev}")
            lines.append("")
        return "\n".join(lines).strip()
