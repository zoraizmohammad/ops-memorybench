"""Storage backend interface.

The platform separates two storage concerns:

- **payloads** live in the content addressed :class:`~ombench.storage.blobstore.BlobStore`
- **metadata and indexes** live in a relational :class:`StorageBackend`

Keeping the relational layer behind a small interface is what lets the local first
SQLite implementation be swapped for Postgres (with ``pgvector`` for embeddings)
without touching the domain stores. Domain code writes portable SQL using ``?``
placeholders; each backend translates them to its own paramstyle. The interface is
deliberately thin: connection lifecycle, parameterized execution, queries that
return plain dict rows, transactions, and a migration runner.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

Row = dict[str, Any]
Params = Sequence[Any]


class StorageBackend(ABC):
    """Abstract relational backend.

    Concrete backends translate the uniform ``?`` placeholder used throughout the
    domain stores into their native paramstyle via :attr:`paramstyle`.
    """

    #: Native parameter marker. SQLite uses ``?``; Postgres uses ``%s``.
    paramstyle: str = "?"

    def translate(self, sql: str) -> str:
        """Translate uniform ``?`` placeholders to the backend paramstyle.

        SQLite needs no translation. A Postgres backend overrides
        :attr:`paramstyle` and this method rewrites the markers.
        """
        if self.paramstyle == "?":
            return sql
        return re.sub(r"\?", self.paramstyle, sql)

    # -- lifecycle --------------------------------------------------------

    @abstractmethod
    def connect(self) -> None:
        """Open the underlying connection. Idempotent."""

    @abstractmethod
    def close(self) -> None:
        """Close the underlying connection."""

    # -- execution --------------------------------------------------------

    @abstractmethod
    def execute(self, sql: str, params: Params = ()) -> None:
        """Execute a single statement."""

    @abstractmethod
    def executemany(self, sql: str, seq_params: Sequence[Params]) -> None:
        """Execute a statement once per parameter tuple."""

    @abstractmethod
    def executescript(self, script: str) -> None:
        """Execute a multi statement script. Used by the migration runner."""

    @abstractmethod
    def query(self, sql: str, params: Params = ()) -> list[Row]:
        """Run a query and return all rows as dicts."""

    def query_one(self, sql: str, params: Params = ()) -> Row | None:
        """Run a query and return the first row or ``None``."""
        rows = self.query(sql, params)
        return rows[0] if rows else None

    @abstractmethod
    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Context manager wrapping a unit of work in a transaction."""
        raise NotImplementedError

    # -- convenience ------------------------------------------------------

    def insert(self, table: str, values: dict[str, Any], *, replace: bool = False) -> None:
        """Insert a row from a column to value mapping.

        Expressed in terms of :meth:`execute` so every backend gets it for free.
        When ``replace`` is true an existing row with the same primary key is
        overwritten, used for idempotent index upserts. The ``INSERT OR REPLACE``
        form is SQLite syntax; a Postgres backend would override this to use
        ``INSERT ... ON CONFLICT ... DO UPDATE``.
        """
        cols = list(values.keys())
        placeholders = ", ".join("?" for _ in cols)
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        sql = f"{verb} INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
        self.execute(sql, [values[c] for c in cols])

    # -- migrations -------------------------------------------------------

    def migrate(self, migrations_dir: str | Path) -> list[str]:
        """Apply any pending ``.sql`` migrations in lexical order.

        A ``schema_migrations`` table records which files have been applied, so the
        runner is idempotent and safe to call on every startup. Returns the list of
        newly applied migration names.
        """
        self.connect()
        self.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {r["name"] for r in self.query("SELECT name FROM schema_migrations")}
        directory = Path(migrations_dir)
        newly: list[str] = []
        for path in sorted(directory.glob("*.sql")):
            if path.name in applied:
                continue
            from ..timeutil import to_iso, utcnow

            # Migration DDL is written with IF NOT EXISTS, and executescript manages
            # its own commit, so it runs outside a transaction() block. The applied
            # marker is recorded immediately after, keeping the runner idempotent.
            self.executescript(path.read_text(encoding="utf-8"))
            self.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (path.name, to_iso(utcnow())),
            )
            newly.append(path.name)
        return newly
