"""SQLite implementation of :class:`StorageBackend`.

SQLite is the local first default. It needs no server, stores the whole platform in
a single file, and supports everything the bitemporal queries require. Rows are
returned as plain dicts via ``sqlite3.Row``. Foreign keys are enabled and WAL mode
is used so reads do not block writes during longer ingests.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .backend import Params, Row, StorageBackend


class SQLiteBackend(StorageBackend):
    """A single file SQLite backend.

    Parameters
    ----------
    path:
        Filesystem path to the database file, or ``":memory:"`` for an in memory
        database (used heavily in tests).
    """

    paramstyle = "?"

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._conn: sqlite3.Connection | None = None

    # -- lifecycle --------------------------------------------------------

    def connect(self) -> None:
        if self._conn is not None:
            return
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread is relaxed because the worker may touch the
        # connection from a helper thread; access is otherwise serialized.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- execution --------------------------------------------------------

    def execute(self, sql: str, params: Params = ()) -> None:
        self.conn.execute(self.translate(sql), tuple(params))
        if not self.conn.in_transaction:
            self.conn.commit()

    def executemany(self, sql: str, seq_params: Sequence[Params]) -> None:
        self.conn.executemany(self.translate(sql), [tuple(p) for p in seq_params])
        if not self.conn.in_transaction:
            self.conn.commit()

    def executescript(self, script: str) -> None:
        self.conn.executescript(script)
        if not self.conn.in_transaction:
            self.conn.commit()

    def query(self, sql: str, params: Params = ()) -> list[Row]:
        cur = self.conn.execute(self.translate(sql), tuple(params))
        rows = cur.fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Row:
        return {k: row[k] for k in row.keys()}

    # -- transactions -----------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Wrap a unit of work. Commits on success, rolls back on exception."""
        conn = self.conn
        # Use an explicit BEGIN so executescript inside the block participates.
        already = conn.in_transaction
        if not already:
            conn.execute("BEGIN")
        try:
            yield
        except Exception:
            conn.rollback()
            raise
        else:
            if not already:
                conn.commit()

    # -- convenience ------------------------------------------------------

    def insert(self, table: str, values: dict[str, Any], *, replace: bool = False) -> None:
        """Insert a row from a column to value mapping.

        When ``replace`` is true an existing row with the same primary key is
        overwritten, which the append only event log never uses but which is handy
        for idempotent index upserts.
        """
        cols = list(values.keys())
        placeholders = ", ".join("?" for _ in cols)
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        sql = (
            f"{verb} INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
        )
        self.execute(sql, [values[c] for c in cols])
