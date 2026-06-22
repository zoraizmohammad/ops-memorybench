"""Identifier and canonicalization utilities.

Two families of identifiers exist in ombench:

1. Content addresses. A SHA-256 over a canonical JSON encoding. These are stable,
   deduplicating, and integrity checking. They underpin the blob store, entity
   version hashes, and snapshot roots, in the spirit of Git objects and IPFS CIDs.

2. Prefixed opaque identifiers. Human readable, prefixed (``trace_``, ``mem_``,
   ``evt_`` and so on). When a stable seed is available we derive them
   deterministically from content so that re ingesting the same data yields the
   same id, which keeps the event log idempotent.

Both rely on :func:`canonical_json`, a deterministic JSON encoder. Determinism is
not a nicety here. It is what makes content addressing and replay correct.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import Enum
from typing import Any

from .timeutil import to_iso


def _default(obj: Any) -> Any:
    """Serialize types the stdlib json encoder does not handle natively."""
    if isinstance(obj, datetime):
        return to_iso(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    # Pydantic models expose model_dump in v2.
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def canonical_json(payload: Any) -> str:
    """Return a deterministic JSON string for ``payload``.

    Keys are sorted, whitespace is compact, and non ASCII is preserved. Two
    semantically equal payloads always produce the same string, which is the
    precondition for content addressing.
    """
    return json.dumps(
        payload,
        default=_default,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def sha256_hex(data: bytes | str) -> str:
    """Return the hex SHA-256 digest of bytes or a UTF-8 string."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def content_hash(payload: Any) -> str:
    """Content address a structured payload via canonical JSON then SHA-256."""
    return sha256_hex(canonical_json(payload))


def short_hash(payload: Any, length: int = 12) -> str:
    """A short content hash for human facing identifiers and filenames."""
    return content_hash(payload)[:length]


def new_id(prefix: str, *, seed: Any | None = None) -> str:
    """Create a prefixed identifier.

    If ``seed`` is provided the suffix is a deterministic short content hash of the
    seed, which makes ingestion idempotent. If ``seed`` is omitted a random suffix
    is used. Determinism is strongly preferred throughout ombench, so callers in
    the ingestion path always pass a seed.
    """
    if seed is not None:
        return f"{prefix}_{short_hash(seed, 16)}"
    # Random fallback for cases where no natural content seed exists. Imported
    # lazily so that the deterministic path carries no dependency on it.
    import secrets

    return f"{prefix}_{secrets.token_hex(8)}"


def is_content_hash(value: str) -> bool:
    """True if ``value`` looks like a 64 character lowercase hex SHA-256 digest."""
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()
