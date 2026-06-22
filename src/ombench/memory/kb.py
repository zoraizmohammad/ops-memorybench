"""The compiled knowledge base filesystem.

The knowledge base is, in practice, a filesystem the agent can read, in the spirit
of gstack and Karpathy's LLM Wiki. Durable knowledge is compiled into human readable
markdown files with YAML frontmatter carrying structured metadata and provenance.
This is deliberately a filesystem and not only a vector index, because a readable,
auditable, diffable knowledge base is far more legible during a demo and far easier
to reason about than an opaque embedding store.

Layout::

    /memory
      /people        one file per person
      /projects      one directory per project
      /norms         team and communication norms
      /procedures    reusable workflows
      /timeline      episodic day files
      /provenance    one json record per memory id

This module owns reading and writing that filesystem. The compiler decides what to
write; this decides how it is laid out and serialized.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..ids import canonical_json
from .schema import MemoryItem, MemoryType, Namespace

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


@dataclass
class KBDocument:
    """A parsed knowledge base markdown document."""

    frontmatter: dict[str, Any]
    body: str
    path: Path | None = None


def parse_markdown(text: str) -> KBDocument:
    """Parse a markdown document with optional YAML frontmatter."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return KBDocument(frontmatter={}, body=text.strip())
    fm = yaml.safe_load(match.group(1)) or {}
    return KBDocument(frontmatter=fm, body=match.group(2).strip())


def render_markdown(frontmatter: dict[str, Any], body: str) -> str:
    """Serialize frontmatter and body into a markdown document."""
    fm = yaml.safe_dump(frontmatter, sort_keys=True, default_flow_style=False).strip()
    return f"---\n{fm}\n---\n\n{body.strip()}\n"


def _slug(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return s or "item"


class KnowledgeBase:
    """Read and write the compiled knowledge base filesystem."""

    SUBDIRS = ("people", "projects", "norms", "procedures", "timeline", "provenance")

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def ensure_layout(self) -> None:
        for sub in self.SUBDIRS:
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    # -- path routing -----------------------------------------------------

    def path_for_subject(self, namespace: Namespace, subject: str) -> Path:
        """Choose the file a subject's knowledge is compiled into."""
        slug = _slug(subject)
        if namespace == Namespace.USER:
            return self.root / "people" / f"{slug}.md"
        if namespace == Namespace.PROJECT:
            return self.root / "projects" / slug / "overview.md"
        if namespace == Namespace.TEAM:
            return self.root / "norms" / f"{slug}.md"
        return self.root / "timeline" / f"{slug}.md"

    # -- writing ----------------------------------------------------------

    def write_document(self, path: Path, frontmatter: dict[str, Any], body: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(frontmatter, body), encoding="utf-8")
        return path

    def write_provenance(self, item: MemoryItem) -> Path:
        """Write the provenance record for a memory item as json."""
        path = self.root / "provenance" / f"{item.memory_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "memory_id": item.memory_id,
            "type": item.type.value,
            "namespace": item.namespace.value,
            "subject": item.subject,
            "claim": item.claim,
            "confidence": item.confidence,
            "ttl_policy": item.ttl_policy.value,
            "acl": item.acl,
            "evidence": [e.model_dump() for e in item.evidence],
            "created_at": item.created_at.isoformat(),
        }
        path.write_text(canonical_json(record), encoding="utf-8")
        return path

    def read_provenance(self, memory_id: str) -> dict[str, Any] | None:
        path = self.root / "provenance" / f"{memory_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # -- reading ----------------------------------------------------------

    def read_document(self, path: Path) -> KBDocument | None:
        if not path.exists():
            return None
        doc = parse_markdown(path.read_text(encoding="utf-8"))
        doc.path = path
        return doc

    def iter_documents(self) -> list[KBDocument]:
        """Read every markdown document in the knowledge base."""
        docs: list[KBDocument] = []
        for path in sorted(self.root.rglob("*.md")):
            doc = self.read_document(path)
            if doc is not None:
                docs.append(doc)
        return docs

    def list_files(self) -> list[Path]:
        return sorted(self.root.rglob("*.md"))

    def mounted_text(self, max_chars: int | None = None) -> str:
        """Return the whole knowledge base concatenated as one readable string.

        This is the simplest form of mounting the knowledge base into an agent: a
        single document the agent can read. The retriever provides a smarter, budget
        aware alternative, but this is useful for small knowledge bases and for the
        with memory condition baseline.
        """
        parts: list[str] = []
        for doc in self.iter_documents():
            rel = doc.path.relative_to(self.root) if doc.path else Path("?")
            parts.append(f"# file {rel}\n\n{doc.body}")
        text = "\n\n---\n\n".join(parts)
        if max_chars is not None and len(text) > max_chars:
            return text[:max_chars]
        return text


# Mapping of memory type to the human readable section heading used when several
# items are grouped into one file.
TYPE_SECTION = {
    MemoryType.SEMANTIC: "Facts and preferences",
    MemoryType.PROCEDURAL: "Procedures",
    MemoryType.EPISODIC: "History",
}
