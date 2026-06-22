"""Tests for the SaaS Git CLI."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from ombench.cli.main import app

runner = CliRunner()
REPO = Path(__file__).resolve().parents[2]


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("OMBENCH_HOME", str(tmp_path / ".ombench"))
    monkeypatch.chdir(REPO)
    assert runner.invoke(app, ["sync", "run", "gcal"]).exit_code == 0


def test_saasgit_log(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    result = runner.invoke(app, ["saasgit", "log", "gcal", "event", "ev_1on1_bob"])
    assert result.exit_code == 0
    assert "history" in result.output
    assert "upsert_entity" in result.output


def test_saasgit_show_time_travel(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    # Before the reschedule the start is 9am.
    early = runner.invoke(app, ["saasgit", "show", "gcal", "event", "ev_1on1_bob",
                                "--at", "2026-05-10T00:00:00Z"])
    assert "09:00" in early.output
    # Latest reflects the 3pm reschedule.
    latest = runner.invoke(app, ["saasgit", "show", "gcal", "event", "ev_1on1_bob"])
    assert "15:00" in latest.output


def test_saasgit_diff(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    result = runner.invoke(app, ["saasgit", "diff", "2026-05-05T00:00:00Z", "2026-06-01T00:00:00Z"])
    assert result.exit_code == 0
    # The 1:1 event changed across the reschedule.
    assert "changed" in result.output or "~" in result.output


def test_saasgit_checkout_and_ls(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    checkout = runner.invoke(app, ["saasgit", "checkout", "2026-06-01T00:00:00Z", "--label", "now"])
    assert checkout.exit_code == 0
    assert "checked out" in checkout.output

    ls = runner.invoke(app, ["saasgit", "ls", "--app-name", "gcal"])
    assert ls.exit_code == 0
    assert "gcal/event/ev_1on1_bob" in ls.output
