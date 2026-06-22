"""ombench.storage subpackage.

Two storage concerns live here: the content addressed :class:`BlobStore` for
payloads, and the relational :class:`StorageBackend` for metadata and indexes. The
:func:`open_store` helper wires both together against a :class:`~ombench.config.Config`
and applies pending migrations, which is the normal way the rest of the platform
obtains storage.
"""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from .backend import Row, StorageBackend
from .blobstore import BlobStore, make_blob_uri, parse_blob_uri
from .sqlite_backend import SQLiteBackend

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

__all__ = [
    "BlobStore",
    "Row",
    "SQLiteBackend",
    "StorageBackend",
    "Store",
    "make_blob_uri",
    "open_memory_store",
    "open_store",
    "parse_blob_uri",
]


class Store:
    """A wired pair of relational backend and blob store.

    This is the handle the domain layers receive. It keeps the two storage
    concerns together so callers do not have to thread two objects everywhere.
    """

    def __init__(self, backend: StorageBackend, blobs: BlobStore) -> None:
        self.backend = backend
        self.blobs = blobs

    def close(self) -> None:
        self.backend.close()


def open_store(config: Config, *, migrate: bool = True) -> Store:
    """Open the relational backend and blob store for a config and migrate.

    The local first default is SQLite plus a filesystem blob store. Swapping in a
    Postgres backend later means changing only this function.
    """
    config.ensure_dirs()
    backend = SQLiteBackend(config.db_path)
    backend.connect()
    if migrate:
        backend.migrate(MIGRATIONS_DIR)
    blobs = BlobStore(config.blobs_dir)
    return Store(backend=backend, blobs=blobs)


def open_memory_store() -> Store:
    """Open a fully in memory store for tests and ephemeral runs."""
    import tempfile

    backend = SQLiteBackend(":memory:")
    backend.connect()
    backend.migrate(MIGRATIONS_DIR)
    blobs = BlobStore(tempfile.mkdtemp(prefix="ombench-blobs-"))
    return Store(backend=backend, blobs=blobs)
