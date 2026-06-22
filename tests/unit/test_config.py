"""Tests for runtime configuration."""

from __future__ import annotations

from pathlib import Path

from ombench.config import Config, load_config


def test_load_config_keyless_defaults(monkeypatch, tmp_path):
    # Clear any credentials that might be present in the real environment.
    for var in [
        "ANTHROPIC_API_KEY",
        "OMBENCH_LLM_PROVIDER",
        "SLACK_BOT_TOKEN",
        "SLACK_SIGNING_SECRET",
        "GOOGLE_CREDENTIALS_FILE",
        "GOOGLE_TOKEN_FILE",
        "OMBENCH_HOME",
    ]:
        monkeypatch.delenv(var, raising=False)

    cfg = load_config(env_file=tmp_path / "does-not-exist.env")
    assert cfg.llm.provider == "stub"
    assert cfg.llm.effective_provider == "stub"
    assert not cfg.slack.is_live
    assert not cfg.google.is_live


def test_anthropic_falls_back_to_stub_without_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OMBENCH_LLM_PROVIDER", "anthropic")
    cfg = load_config(env_file=tmp_path / "none.env")
    assert cfg.llm.provider == "anthropic"
    assert cfg.llm.effective_provider == "stub"


def test_anthropic_active_with_key(monkeypatch, tmp_path):
    monkeypatch.setenv("OMBENCH_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    cfg = load_config(env_file=tmp_path / "none.env")
    assert cfg.llm.has_anthropic
    assert cfg.llm.effective_provider == "anthropic"


def test_slack_and_google_live_flags(monkeypatch, tmp_path):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-123")
    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", "/tmp/creds.json")
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", "/tmp/token.json")
    cfg = load_config(env_file=tmp_path / "none.env")
    assert cfg.slack.is_live
    assert cfg.google.is_live


def test_derived_paths(tmp_path):
    cfg = Config(home=tmp_path / ".ombench", repo_root=tmp_path)
    assert cfg.db_path == tmp_path / ".ombench" / "ombench.db"
    assert cfg.blobs_dir == tmp_path / ".ombench" / "blobs"
    assert cfg.kb_dir == tmp_path / ".ombench" / "memory"
    assert cfg.fixtures_dir == tmp_path / "fixtures"


def test_ensure_dirs_creates_store(tmp_path):
    cfg = Config(home=tmp_path / ".ombench", repo_root=tmp_path)
    cfg.ensure_dirs()
    assert cfg.home.exists()
    assert cfg.blobs_dir.exists()
    assert isinstance(cfg.repo_root, Path)
