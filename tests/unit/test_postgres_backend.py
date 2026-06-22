"""Tests for the Postgres backend dialect logic.

The live round trip requires a running Postgres and is marked ``live`` so the keyless
suite skips it. The dialect logic (placeholder translation and ON CONFLICT insert
generation) is tested here without a database by capturing the SQL the backend would
execute, which is where the SQLite vs Postgres differences actually live.
"""

from __future__ import annotations

from ombench.storage.postgres_backend import PostgresBackend


class _FakeCursor:
    def __init__(self, sink):
        self._sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self._sink.append((sql, tuple(params)))

    def executemany(self, sql, seq):
        self._sink.append((sql, list(seq)))


class _FakeConn:
    def __init__(self):
        self.statements: list = []

    def cursor(self):
        return _FakeCursor(self.statements)

    def execute(self, sql, params=()):
        self.statements.append((sql, tuple(params)))


def _backend_with_fake_conn():
    b = PostgresBackend("postgresql://localhost/test")
    b._conn = _FakeConn()
    return b


def test_paramstyle_is_percent_s():
    assert PostgresBackend.paramstyle == "%s"


def test_translate_rewrites_placeholders():
    b = PostgresBackend("postgresql://localhost/test")
    assert b.translate("SELECT * FROM t WHERE a = ? AND b = ?") == (
        "SELECT * FROM t WHERE a = %s AND b = %s"
    )


def test_plain_insert_uses_percent_s():
    b = _backend_with_fake_conn()
    b.insert("app_events", {"event_id": "e1", "app": "slack"})
    sql, params = b._conn.statements[-1]
    assert "INSERT INTO app_events" in sql
    assert "VALUES (%s, %s)" in sql
    assert "ON CONFLICT" not in sql
    assert params == ("e1", "slack")


def test_replace_insert_emits_on_conflict(monkeypatch):
    b = _backend_with_fake_conn()
    # Stub the primary key lookup so we do not need a live catalog.
    monkeypatch.setattr(b, "_primary_key", lambda table: "snapshot_id")
    b.insert("snapshot_manifests", {"snapshot_id": "s1", "root_hash": "h"}, replace=True)
    sql, params = b._conn.statements[-1]
    assert "ON CONFLICT (snapshot_id) DO UPDATE SET" in sql
    assert "root_hash = EXCLUDED.root_hash" in sql
    assert params == ("s1", "h")


def test_execute_translates_question_marks():
    b = _backend_with_fake_conn()
    b.execute("DELETE FROM t WHERE id = ?", ("x",))
    sql, params = b._conn.statements[-1]
    assert sql == "DELETE FROM t WHERE id = %s"
    assert params == ("x",)


def test_missing_driver_raises_clear_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psycopg":
            raise ImportError("no psycopg")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    b = PostgresBackend("postgresql://localhost/test")
    try:
        b.connect()
        raised = False
    except RuntimeError as exc:
        raised = "psycopg is required" in str(exc)
    assert raised
