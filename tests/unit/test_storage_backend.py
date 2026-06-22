"""Tests for the relational storage backend and migrations."""

from __future__ import annotations

import pytest

from ombench.storage import MIGRATIONS_DIR, open_memory_store, open_store
from ombench.storage.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend():
    b = SQLiteBackend(":memory:")
    b.connect()
    yield b
    b.close()


def test_migrate_is_idempotent(backend):
    applied_first = backend.migrate(MIGRATIONS_DIR)
    assert "0001_initial.sql" in applied_first
    applied_second = backend.migrate(MIGRATIONS_DIR)
    assert applied_second == []


def test_tables_exist_after_migration(backend):
    backend.migrate(MIGRATIONS_DIR)
    rows = backend.query("SELECT name FROM sqlite_master WHERE type='table'")
    names = {r["name"] for r in rows}
    for expected in [
        "app_events",
        "trace_runs",
        "trace_spans",
        "snapshot_manifests",
        "memory_items",
        "task_specs",
        "replay_results",
        "schema_migrations",
    ]:
        assert expected in names


def test_insert_and_query(backend):
    backend.migrate(MIGRATIONS_DIR)
    backend.insert(
        "sync_cursors",
        {"app": "slack", "stream": "C1", "cursor": "tok", "updated_at": "2026-01-01T00:00:00.000Z"},
    )
    row = backend.query_one(
        "SELECT cursor FROM sync_cursors WHERE app = ? AND stream = ?", ("slack", "C1")
    )
    assert row is not None
    assert row["cursor"] == "tok"


def test_query_one_returns_none_when_empty(backend):
    backend.migrate(MIGRATIONS_DIR)
    assert backend.query_one("SELECT * FROM app_events") is None


def test_transaction_commits(backend):
    backend.migrate(MIGRATIONS_DIR)
    with backend.transaction():
        backend.insert(
            "sync_cursors",
            {"app": "a", "stream": "s", "cursor": "c", "updated_at": "t"},
        )
    assert backend.query_one("SELECT * FROM sync_cursors") is not None


def test_transaction_rolls_back_on_error(backend):
    backend.migrate(MIGRATIONS_DIR)
    with pytest.raises(RuntimeError):
        with backend.transaction():
            backend.insert(
                "sync_cursors",
                {"app": "a", "stream": "s", "cursor": "c", "updated_at": "t"},
            )
            raise RuntimeError("boom")
    assert backend.query_one("SELECT * FROM sync_cursors") is None


def test_insert_or_replace(backend):
    backend.migrate(MIGRATIONS_DIR)
    backend.insert(
        "sync_cursors", {"app": "a", "stream": "s", "cursor": "v1", "updated_at": "t"}
    )
    backend.insert(
        "sync_cursors",
        {"app": "a", "stream": "s", "cursor": "v2", "updated_at": "t"},
        replace=True,
    )
    row = backend.query_one("SELECT cursor FROM sync_cursors WHERE app='a' AND stream='s'")
    assert row["cursor"] == "v2"


def test_translate_passthrough_for_sqlite(backend):
    assert backend.translate("SELECT ?") == "SELECT ?"


def test_open_store_on_disk(config):
    store = open_store(config)
    assert store.backend.query_one("SELECT 1 AS x")["x"] == 1
    # The blob store is wired and usable.
    digest = store.blobs.put_text("hi")
    assert store.blobs.get_text(digest) == "hi"
    store.close()
    assert config.db_path.exists()


def test_open_memory_store():
    store = open_memory_store()
    assert store.backend.query_one("SELECT 1 AS x")["x"] == 1
    store.close()
