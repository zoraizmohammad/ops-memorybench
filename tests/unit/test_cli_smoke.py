"""Smoke tests for the CLI entrypoint."""

from __future__ import annotations

from typer.testing import CliRunner

from ombench import __version__
from ombench.cli.main import app

runner = CliRunner()


def test_version_command():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_info_command(monkeypatch):
    for var in ["ANTHROPIC_API_KEY", "SLACK_BOT_TOKEN", "GOOGLE_CREDENTIALS_FILE"]:
        monkeypatch.delenv(var, raising=False)
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    assert "configuration" in result.stdout.lower()


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    # no_args_is_help exits with code 0 after printing help.
    assert "ombench" in result.stdout.lower()
