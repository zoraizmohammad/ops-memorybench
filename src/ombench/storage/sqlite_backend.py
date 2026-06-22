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
        #
        # isolation_level=None puts the driver in autocommit mode. Without this,
        # sqlite3 implicitly opens a transaction on the first DML statement and
        # never commits it unless told to, which silently loses single statement
        # writes across process boundaries. With autocommit, statements outside an
        # explicit transaction() block commit immediately, and transaction() drives
        # BEGIN and COMMIT itself.
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
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
        # In autocommit mode a statement outside a transaction() block commits
        # immediately; inside one it joins the open transaction.
        self.conn.execute(self.translate(sql), tuple(params))

    def executemany(self, sql: str, seq_params: Sequence[Params]) -> None:
        self.conn.executemany(self.translate(sql), [tuple(p) for p in seq_params])

    def executescript(self, script: str) -> None:
        # sqlite3.executescript commits any pending transaction before running, so
        # it is used only outside transaction() blocks (the migration runner calls
        # it directly). The schema is written with IF NOT EXISTS so re running is
        # safe even if a later step fails.
        self.conn.executescript(script)

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
        """Wrap a unit of work. Commits on success, rolls back on exception.

        Nested calls are flattened: only the outermost block drives BEGIN and
        COMMIT, so helpers that open their own transaction compose safely.
        """
        conn = self.conn
        already = conn.in_transaction
        if not already:
            conn.execute("BEGIN")
        try:
            yield
        except Exception:
            if not already:
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
