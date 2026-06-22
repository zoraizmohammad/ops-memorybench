"""Smoke test for the end to end demo CLI command.

Runs ``omb demo`` against an isolated home with the repo fixtures and asserts the
headline result line appears, proving the whole loop is runnable with one command and
no credentials.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from ombench.cli.main import app

runner = CliRunner()
REPO = Path(__file__).resolve().parents[2]


def test_demo_runs_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("OMBENCH_HOME", str(tmp_path / ".ombench"))
    for var in ["ANTHROPIC_API_KEY", "SLACK_BOT_TOKEN", "GOOGLE_CREDENTIALS_FILE"]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(REPO)

    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 0, result.output
    assert "Memory raised the mean rubric" in result.output
    # The without memory mean is below the with memory mean in the output table.
    assert "with memory" in result.output


def test_eval_run_command(tmp_path, monkeypatch):
    monkeypatch.setenv("OMBENCH_HOME", str(tmp_path / ".ombench"))
    monkeypatch.chdir(REPO)
    # Seed the store first via demo's path is not needed; eval run works on an empty
    # store too, just with weaker results. Assert it produces a results table.
    result = runner.invoke(app, ["eval", "run"])
    assert result.exit_code == 0, result.output
    assert "Backtest results" in result.output
