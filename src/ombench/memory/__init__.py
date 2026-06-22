"""ombench.memory subpackage.

The knowledge base compiler and hybrid retrieval. History is turned into durable
memory items by the extractor, scorer, resolver, and compiler, written to the
readable knowledge base filesystem, and served at runtime by the hybrid retriever.
"""

from __future__ import annotations

from .bootstrap import ColdStartBootstrapper
from .compiler import CompileResult, KnowledgeCompiler
from .kb import KnowledgeBase
from .retriever import MemoryBundle, MemoryRetriever
from .schema import (
    EvidenceRef,
    MemoryItem,
    MemoryType,
    Namespace,
    TTLPolicy,
)
from .store import MemoryStore

__all__ = [
    "ColdStartBootstrapper",
    "CompileResult",
    "EvidenceRef",
    "KnowledgeBase",
    "KnowledgeCompiler",
    "MemoryBundle",
    "MemoryItem",
    "MemoryRetriever",
    "MemoryStore",
    "MemoryType",
    "Namespace",
    "TTLPolicy",
]
