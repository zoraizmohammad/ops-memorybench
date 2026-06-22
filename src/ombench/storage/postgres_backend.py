"""PostgreSQL implementation of :class:`StorageBackend`.

This is the production storage swap the platform is designed for. It implements the
same thin interface the SQLite backend does, so the domain stores (events, traces,
snapshots, memory, eval) run against Postgres without any change above this layer.
The driver (``psycopg`` 3) is imported lazily inside the constructor so importing
this module never affects the keyless local first path, which uses SQLite.

Two dialect differences are handled here:

- the parameter marker is ``%s`` rather than ``?`` (the base class translation
  rewrites the uniform ``?`` placeholders used by the domain SQL)
- ``INSERT OR REPLACE`` is SQLite syntax, so :meth:`insert` with ``replace`` is
  overridden to emit ``INSERT ... ON CONFLICT DO UPDATE``

The schema migrations are written with ``IF NOT EXISTS`` and types (``TEXT``,
``INTEGER``, ``REAL``) that Postgres accepts, so the same migration files apply.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from .backend import Params, Row, StorageBackend


class PostgresBackend(StorageBackend):
    """A PostgreSQL backend implementing the storage interface.

    Parameters
    ----------
    dsn:
        A libpq connection string or URL, for example
        ``postgresql://ombench:ombench@localhost:5432/ombench``.
    """

    paramstyle = "%s"

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._conn: Any | None = None

    # -- lifecycle --------------------------------------------------------

    def connect(self) -> None:
        if self._conn is not None:
            return
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - exercised only without driver
            raise RuntimeError(
                "psycopg is required for the Postgres backend. Install it with "
                "pip install 'psycopg[binary]'."
            ) from exc
        # autocommit mirrors the SQLite backend: statements outside a transaction()
        # block commit immediately, and transaction() drives BEGIN/COMMIT itself.
        self._conn = psycopg.connect(self.dsn, autocommit=True)

    @property
    def conn(self) -> Any:
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
        with self.conn.cursor() as cur:
            cur.execute(self.translate(sql), tuple(params))

    def executemany(self, sql: str, seq_params: Sequence[Params]) -> None:
        with self.conn.cursor() as cur:
            cur.executemany(self.translate(sql), [tuple(p) for p in seq_params])

    def executescript(self, script: str) -> None:
        # psycopg can execute a multi statement string in one call.
        with self.conn.cursor() as cur:
            cur.execute(script)

    def query(self, sql: str, params: Params = ()) -> list[Row]:
        with self.conn.cursor() as cur:
            cur.execute(self.translate(sql), tuple(params))
            cols = [d.name for d in cur.description] if cur.description else []
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    # -- transactions -----------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Wrap a unit of work. Commits on success, rolls back on exception.

        Uses a libpq transaction via the connection's own context manager. Nested
        calls are flattened by tracking depth so helpers that open their own
        transaction compose safely, matching the SQLite backend semantics.
        """
        conn = self.conn
        depth = getattr(self, "_txn_depth", 0)
        if depth == 0:
            conn.execute("BEGIN")
        self._txn_depth = depth + 1
        try:
            yield
        except Exception:
            if depth == 0:
                conn.execute("ROLLBACK")
            self._txn_depth = depth
            raise
        else:
            if depth == 0:
                conn.execute("COMMIT")
            self._txn_depth = depth

    # -- convenience ------------------------------------------------------

    def insert(self, table: str, values: dict[str, Any], *, replace: bool = False) -> None:
        """Insert a row, using Postgres ON CONFLICT for the replace path.

        The base class implementation emits SQLite's ``INSERT OR REPLACE``; Postgres
        needs ``INSERT ... ON CONFLICT DO UPDATE``. The conflict target is left to
        the table's primary key by using a bare ``ON CONFLICT`` is not valid, so the
        non replace path is a plain insert and the replace path updates every column
        on any primary key conflict.
        """
        cols = list(values.keys())
        placeholders = ", ".join("%s" for _ in cols)
        col_list = ", ".join(cols)
        if not replace:
            sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
            self.execute(sql, [values[c] for c in cols])
            return
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
        # The primary key column is discovered from the catalog so the conflict
        # target is correct for any table.
        pk = self._primary_key(table)
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({pk}) DO UPDATE SET {updates}"
        )
        # execute() translates ? markers; this SQL already uses %s, so call directly.
        with self.conn.cursor() as cur:
            cur.execute(sql, tuple(values[c] for c in cols))

    def _primary_key(self, table: str) -> str:
        """Return the comma separated primary key column list for a table."""
        rows = self.query(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = %s::regclass AND i.indisprimary",
            (table,),
        )
        return ", ".join(r["attname"] for r in rows) or "id"
