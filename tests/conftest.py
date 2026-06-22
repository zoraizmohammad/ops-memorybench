"""Shared pytest fixtures.

These fixtures give every test an isolated, deterministic environment: a temporary
``home`` directory for the local store, a frozen clock, and a fresh config that
points at the repository's bundled synthetic fixtures.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ombench.config import Config
from ombench.timeutil import UTC, FrozenClock

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def frozen_clock() -> FrozenClock:
    """A clock pinned to a fixed instant used across deterministic tests."""
    return FrozenClock(datetime(2026, 5, 14, 17, 0, 0, tzinfo=UTC))


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """A config rooted in a temporary directory but pointed at repo fixtures."""
    cfg = Config(home=tmp_path / ".ombench", repo_root=REPO_ROOT)
    cfg.ensure_dirs()
    return cfg
