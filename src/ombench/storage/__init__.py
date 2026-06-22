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
    "PostgresBackend",
    "Row",
    "SQLiteBackend",
    "StorageBackend",
    "Store",
    "make_blob_uri",
    "open_memory_store",
    "open_store",
    "parse_blob_uri",
]


def __getattr__(name: str):
    # Lazy export so importing ombench.storage never imports psycopg.
    if name == "PostgresBackend":
        from .postgres_backend import PostgresBackend

        return PostgresBackend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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

    The local first default is SQLite plus a filesystem blob store. Setting
    ``database_url`` (env ``OMBENCH_DATABASE_URL``) to a Postgres DSN selects the
    production backend behind the same interface; nothing above this function
    changes. The blob store stays filesystem based, which an object store backed
    BlobStore would replace in a full production deployment.
    """
    config.ensure_dirs()
    backend: StorageBackend
    if config.database_url:
        from .postgres_backend import PostgresBackend

        backend = PostgresBackend(config.database_url)
    else:
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
