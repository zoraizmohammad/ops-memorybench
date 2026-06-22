"""Tests for the integration registry.

The registry is the single source of truth for which apps the platform can sync, and
it is what makes adding a new app a drop in. These tests pin that contract.
"""

from __future__ import annotations

from pathlib import Path

from ombench.config import Config
from ombench.integrations.base import Integration
from ombench.integrations.registry import (
    DEFAULT_APPS,
    REGISTRY,
    build_integration,
)
from ombench.storage import open_memory_store

REPO = Path(__file__).resolve().parents[2]


def test_registry_has_all_four_apps():
    assert set(REGISTRY) == {"slack", "gcal", "gdocs", "gmail"}
    # Every registered class is a real Integration subclass.
    for spec in REGISTRY.values():
        assert issubclass(spec.cls, Integration)


def test_gmail_is_in_default_apps():
    # Gmail was previously not wired into the worker/CLI; the registry fixes that.
    assert "gmail" in DEFAULT_APPS


def test_build_integration_from_registry():
    store = open_memory_store()
    config = Config(repo_root=REPO)
    integ = build_integration("gmail", store, config)
    assert integ.app.value == "gmail"
    result = integ.run_sync()
    assert result.events_new > 0
    store.close()


def test_every_default_app_syncs():
    store = open_memory_store()
    config = Config(repo_root=REPO)
    for name in DEFAULT_APPS:
        integ = build_integration(name, store, config)
        result = integ.run_sync()
        assert result.events_new > 0, f"{name} produced no events"
    store.close()
