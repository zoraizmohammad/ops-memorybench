"""Cold start bootstrapping.

Before many trajectories exist the knowledge base would be empty and useless. The
cold start path jump starts it from a team's existing integration data so it is
useful from day one. This extracts durable facts, contacts, conventions, and project
context directly from the synced Slack, Calendar, and Docs state, with lower
confidence than user confirmed knowledge but enough to help.

This is a thin orchestration over the compiler's app state extraction plus a few
structured extractors that pull obvious facts (a person's timezone, a channel's
purpose, a document's owner) that are reliable enough to seed without natural language
detection.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..events.store import EventStore
from ..storage import Store
from .compiler import KnowledgeCompiler
from .schema import EvidenceRef, MemoryItem, MemoryType, Namespace, TTLPolicy
from .store import MemoryStore


@dataclass
class BootstrapResult:
    structured_facts: int = 0
    convention_candidates: int = 0
    total_promoted: int = 0


class ColdStartBootstrapper:
    """Seeds the knowledge base from existing integration data."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.events = EventStore(store.backend, store.blobs)
        self.memory = MemoryStore(store)

    def bootstrap(self, *, kb_root=None, write_files: bool = True) -> BootstrapResult:
        """Run structured fact extraction then the compiler's app state path."""
        result = BootstrapResult()

        # 1. Structured, high reliability facts from current state.
        for item in self._structured_facts():
            self.memory.add(item)
            result.structured_facts += 1

        # 2. Natural language conventions via the compiler app state extractor.
        compiler = KnowledgeCompiler(self.store)
        compile_result = compiler.compile(
            runs=[], include_app_state=True, kb_root=kb_root, write_files=write_files
        )
        result.convention_candidates = compile_result.candidates
        result.total_promoted = result.structured_facts + compile_result.promoted
        return result

    def _structured_facts(self) -> list[MemoryItem]:
        """Pull obvious, reliable facts that need no language understanding."""
        items: list[MemoryItem] = []
        states = self.events.materialize()
        for (app, entity_type, entity_id), state in states.items():
            if app == "slack" and entity_type == "user":
                tz = state.payload.get("tz")
                name = state.payload.get("real_name") or state.payload.get("name")
                if tz and name:
                    items.append(MemoryItem(
                        type=MemoryType.SEMANTIC, namespace=Namespace.USER, subject=name,
                        claim=f"{name} is in timezone {tz}", confidence=0.7,
                        ttl_policy=TTLPolicy.LONG, acl="team",
                        evidence=[EvidenceRef(kind="event", ref=entity_id, note="slack user profile")],
                        tags=["bootstrap", "contact"],
                    ))
            elif app == "slack" and entity_type == "channel":
                name = state.payload.get("name")
                topic = state.payload.get("topic")
                if name and topic:
                    items.append(MemoryItem(
                        type=MemoryType.SEMANTIC, namespace=Namespace.TEAM, subject="channels",
                        claim=f"Channel {name} is for {topic}", confidence=0.65,
                        ttl_policy=TTLPolicy.MEDIUM, acl="team",
                        evidence=[EvidenceRef(kind="event", ref=entity_id, note="slack channel topic")],
                        tags=["bootstrap", "channel"],
                    ))
            elif app == "gdocs" and entity_type == "document":
                owners = state.payload.get("owners", [])
                name = state.payload.get("name")
                if owners and name:
                    items.append(MemoryItem(
                        type=MemoryType.SEMANTIC, namespace=Namespace.PROJECT, subject=name,
                        claim=f"Document {name} is owned by {owners[0]}", confidence=0.6,
                        ttl_policy=TTLPolicy.MEDIUM, acl="project",
                        evidence=[EvidenceRef(kind="event", ref=entity_id, note="drive document owner")],
                        tags=["bootstrap", "document"],
                    ))
        return items
