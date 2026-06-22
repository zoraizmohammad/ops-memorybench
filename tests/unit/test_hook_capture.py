"""Tests for the Claude Code hook capture entrypoint."""

from __future__ import annotations

import json

import pytest

from ombench.config import load_config
from ombench.storage import open_store
from ombench.traces import hook as hookmod
from ombench.traces.ingest import TrajectoryIngestor
from ombench.traces.schema import SpanKind


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    # Point the hook at an isolated home and clear credentials.
    monkeypatch.setenv("OMBENCH_HOME", str(tmp_path / ".ombench"))
    for var in ["ANTHROPIC_API_KEY", "SLACK_BOT_TOKEN", "GOOGLE_CREDENTIALS_FILE"]:
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def _event(name, **kw):
    return {"session_id": "sess1", "hook_event_name": name, **kw}


def test_append_event_writes_log(_home):
    config = load_config()
    hookmod.append_event(config.home, "sess1", _event("UserPromptSubmit", prompt="hi"))
    path = hookmod.capture_path(config.home, "sess1")
    assert path.exists()
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["prompt"] == "hi"


def test_full_hook_sequence_finalizes_trajectory(_home):
    # Simulate a real session: prompt, tool use, stop.
    hookmod.handle(_event("UserPromptSubmit", prompt="Reschedule my 1:1 with Bob"))
    hookmod.handle(_event(
        "PostToolUse", tool_name="gcal.update_event",
        tool_input={"event_id": "ev_1on1", "start": "2026-05-20T15:00:00Z"},
        tool_response={"ok": True},
    ))
    result = hookmod.handle(_event("Stop", transcript_path=""))
    trace_id = result["finalized"]
    assert trace_id is not None

    config = load_config()
    store = open_store(config)
    try:
        run = TrajectoryIngestor(store).load(trace_id)
        assert run is not None
        assert run.agent == "claude_code"
        users = run.spans_of(SpanKind.USER)
        assert any("Bob" in (s.input or "") for s in users)
        tools = run.spans_of(SpanKind.TOOL)
        assert len(tools) == 1
        assert tools[0].tool_name == "gcal.update_event"
        # App ref inferred with write role.
        assert tools[0].app_refs[0].entity_id == "ev_1on1"
        assert tools[0].app_refs[0].role == "write"
    finally:
        store.close()


def test_finalize_prefers_transcript(_home, tmp_path):
    # Provide a transcript file; finalize should use it over the hook log.
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("\n".join([
        json.dumps({"role": "user", "timestamp": "2026-05-14T17:00:00.000Z",
                    "content": "post the launch note"}),
        json.dumps({"role": "assistant", "timestamp": "2026-05-14T17:00:05.000Z",
                    "content": [{"type": "tool_use", "id": "tu1", "name": "slack.post_message",
                                 "input": {"channel": "C1", "text": "launched"}}]}),
        json.dumps({"role": "user", "timestamp": "2026-05-14T17:00:06.000Z",
                    "content": [{"type": "tool_result", "tool_use_id": "tu1",
                                 "content": [{"type": "text", "text": "{\"ok\": true}"}]}]}),
    ]))
    hookmod.handle(_event("UserPromptSubmit", prompt="post the launch note"))
    result = hookmod.handle(_event("Stop", transcript_path=str(transcript)))
    trace_id = result["finalized"]

    config = load_config()
    store = open_store(config)
    try:
        run = TrajectoryIngestor(store).load(trace_id)
        tools = run.spans_of(SpanKind.TOOL)
        assert tools[0].tool_name == "slack.post_message"
    finally:
        store.close()


def test_finalize_empty_session_returns_none(_home):
    result = hookmod.handle(_event("Stop", transcript_path=""))
    assert result["finalized"] is None


def test_main_reads_stdin(_home, monkeypatch, capsys):
    payload = json.dumps(_event("UserPromptSubmit", prompt="hello"))
    monkeypatch.setattr("sys.stdin", _FakeStdin(payload))
    code = hookmod.main()
    assert code == 0
    out = capsys.readouterr().out
    assert "captured" in out


def test_main_handles_empty_stdin(_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", _FakeStdin(""))
    assert hookmod.main() == 0


def test_main_never_raises_on_bad_json(_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", _FakeStdin("{not valid json"))
    # Capture must never block work, so a parse error still exits 0.
    assert hookmod.main() == 0


class _FakeStdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text
