"""Smoke tests across the remaining CLI command groups and the app entrypoints.

These exercise the operator surface end to end against an isolated home and the repo
fixtures, covering the command wrappers that the unit tests do not reach.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ombench.apps.replay.replay_runner import run_backtest
from ombench.apps.worker.sync_worker import run_once
from ombench.cli.main import app
from ombench.config import Config

runner = CliRunner()
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("OMBENCH_HOME", str(tmp_path / ".ombench"))
    for var in ["ANTHROPIC_API_KEY", "SLACK_BOT_TOKEN", "GOOGLE_CREDENTIALS_FILE"]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(REPO)


def test_trace_ingest_list_show():
    fixture = "fixtures/trajectories/claude_code_reschedule.jsonl"
    assert runner.invoke(app, ["trace", "ingest", fixture]).exit_code == 0
    listed = runner.invoke(app, ["trace", "list"])
    assert listed.exit_code == 0
    assert "captured trajectories" in listed.output


def test_sync_and_snapshot_and_memory_flow():
    assert runner.invoke(app, ["sync", "run", "all"]).exit_code == 0
    assert runner.invoke(app, ["snapshot", "create", "--label", "now"]).exit_code == 0
    listed = runner.invoke(app, ["snapshot", "list"])
    assert "snapshots" in listed.output
    assert runner.invoke(app, ["memory", "bootstrap"]).exit_code == 0
    mem = runner.invoke(app, ["memory", "list"])
    assert mem.exit_code == 0
    ret = runner.invoke(app, ["memory", "retrieve", "what time do I prefer"])
    assert ret.exit_code == 0


def test_eval_mine_command():
    runner.invoke(app, ["trace", "ingest", "fixtures/trajectories/claude_code_reschedule.jsonl"])
    result = runner.invoke(app, ["eval", "mine"])
    assert result.exit_code == 0


def test_viz_provenance_and_timetravel():
    runner.invoke(app, ["sync", "run", "gcal"])
    runner.invoke(app, ["memory", "bootstrap"])
    prov = runner.invoke(app, ["viz", "provenance"])
    assert prov.exit_code == 0
    tt = runner.invoke(app, ["viz", "timetravel", "gcal", "event", "ev_1on1_bob"])
    assert tt.exit_code == 0


def test_worker_run_once(tmp_path):
    config = Config(home=tmp_path / ".ombench-worker", repo_root=REPO)
    results = run_once(config)
    assert results["slack"] > 0
    assert results["gcal"] > 0
    # Re running is idempotent: no new events.
    again = run_once(config)
    assert all(v == 0 for v in again.values())


def test_replay_runner(tmp_path):
    config = Config(home=tmp_path / ".ombench-replay", repo_root=REPO)
    report = run_backtest(config)
    assert len(report.results) == 15
    # Win rate is on the outcome grounded delta; one task is neutral, fourteen win.
    assert report.win_rate() >= 0.9
