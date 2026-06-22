"""Content addressed blob store.

Payloads are stored by the SHA-256 of their bytes. For structured payloads the
bytes are the canonical JSON encoding, so two semantically equal objects share one
blob. This gives, in the spirit of Git objects and IPFS content identifiers:

- deduplication: identical content is stored once
- integrity: a fetched blob can be re verified against its address
- cheap snapshots: a snapshot manifest only needs to point at hashes
- immutability: a content address always denotes the same bytes

Blobs live on disk under a two character fanout directory (``ab/cdef...``) exactly
like Git's loose object layout, which keeps any single directory small. A
``blob://<hash>`` URI is the portable reference stored in events and manifests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..ids import canonical_json, is_content_hash, sha256_hex

BLOB_URI_PREFIX = "blob://"


class BlobNotFoundError(KeyError):
    """Raised when a referenced blob is not present in the store."""


class BlobIntegrityError(ValueError):
    """Raised when stored bytes do not match their content address."""


def make_blob_uri(digest: str) -> str:
    """Return the ``blob://`` URI for a content hash."""
    return f"{BLOB_URI_PREFIX}{digest}"


def parse_blob_uri(uri: str) -> str:
    """Extract the content hash from a ``blob://`` URI.

    Accepts a bare hash as well so callers can be lenient about which form they
    received.
    """
    digest = uri[len(BLOB_URI_PREFIX) :] if uri.startswith(BLOB_URI_PREFIX) else uri
    if not is_content_hash(digest):
        raise ValueError(f"Not a valid blob reference: {uri!r}")
    return digest


class BlobStore:
    """A filesystem backed content addressed store.

    Parameters
    ----------
    root:
        Directory under which loose blob objects are written.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- internal helpers -------------------------------------------------

    def _path_for(self, digest: str) -> Path:
        # Git style fanout: first two hex chars name a subdirectory.
        return self.root / digest[:2] / digest[2:]

    # -- writes -----------------------------------------------------------

    def put_bytes(self, data: bytes) -> str:
        """Store raw bytes and return their content hash.

        Writing the same bytes twice is a no op beyond the hash computation, which
        is what makes ingestion idempotent and deduplicating. The write is atomic:
        bytes land in a temporary file that is then renamed into place.
        """
        digest = sha256_hex(data)
        path = self._path_for(digest)
        if path.exists():
            return digest
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        return digest

    def put_text(self, text: str) -> str:
        """Store a UTF-8 string and return its content hash."""
        return self.put_bytes(text.encode("utf-8"))

    def put_json(self, payload: Any) -> str:
        """Store a structured payload as canonical JSON and return its hash.

        Because canonical JSON is deterministic, equal payloads always address the
        same blob. This is the method most of the platform uses.
        """
        return self.put_text(canonical_json(payload))

    # -- reads ------------------------------------------------------------

    def get_bytes(self, ref: str, *, verify: bool = True) -> bytes:
        """Return the bytes for a content hash or ``blob://`` URI.

        With ``verify`` true the bytes are re hashed and checked against the
        requested address, surfacing any on disk corruption immediately.
        """
        digest = parse_blob_uri(ref)
        path = self._path_for(digest)
        if not path.exists():
            raise BlobNotFoundError(digest)
        data = path.read_bytes()
        if verify and sha256_hex(data) != digest:
            raise BlobIntegrityError(
                f"Blob {digest} failed integrity check, content has changed on disk"
            )
        return data

    def get_text(self, ref: str, *, verify: bool = True) -> str:
        return self.get_bytes(ref, verify=verify).decode("utf-8")

    def get_json(self, ref: str, *, verify: bool = True) -> Any:
        import json

        return json.loads(self.get_text(ref, verify=verify))

    # -- queries ----------------------------------------------------------

    def exists(self, ref: str) -> bool:
        try:
            digest = parse_blob_uri(ref)
        except ValueError:
            return False
        return self._path_for(digest).exists()

    def size(self, ref: str) -> int:
        """Return the on disk size in bytes of a stored blob."""
        digest = parse_blob_uri(ref)
        path = self._path_for(digest)
        if not path.exists():
            raise BlobNotFoundError(digest)
        return path.stat().st_size

    def iter_digests(self):
        """Yield every content hash present in the store.

        Useful for garbage collection and integrity sweeps.
        """
        for sub in sorted(self.root.iterdir()):
            if not sub.is_dir() or len(sub.name) != 2:
                continue
            for obj in sorted(sub.iterdir()):
                if obj.suffix == ".tmp":
                    continue
                yield sub.name + obj.name

    def verify_all(self) -> list[str]:
        """Re hash every blob and return the list of corrupted digests."""
        corrupted: list[str] = []
        for digest in self.iter_digests():
            data = self._path_for(digest).read_bytes()
            if sha256_hex(data) != digest:
                corrupted.append(digest)
        return corrupted
