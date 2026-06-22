"""Claude Code hook capture entrypoint.

This is the runtime side of trajectory capture (prompt task 1). Claude Code invokes
configured hooks with a JSON payload on stdin. This module is the command those
hooks run. It accumulates the events of one session incrementally into a per session
capture log, and on session end builds a :class:`~ombench.traces.schema.TraceRun` and
ingests it into the history substrate.

Two capture paths are supported and combined for robustness:

- **Incremental hook events.** ``UserPromptSubmit``, ``PreToolUse``, ``PostToolUse``,
  and ``Stop`` payloads are appended to ``OMBENCH_HOME/captures/<session>.jsonl`` as
  they fire. This works even if the transcript file is unavailable.
- **Transcript reconciliation.** On ``Stop`` or ``SessionEnd`` the ``transcript_path``
  is read when present and converted with the Claude Code converter, which gives the
  richest record. The hook log is used as a fallback when no transcript exists.

The hook never blocks the agent: it always exits 0 and swallows its own errors to a
log line, because a capture failure must never interrupt real operational work.

It is invoked as ``python -m ombench.traces.hook`` (configured by the bundled
plugin) or via the ``omb trace hook`` command.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..config import load_config
from ..logging import get_logger
from ..storage import open_store
from ..timeutil import to_iso, utcnow
from .converters import from_claude_code_session, infer_app_refs
from .ingest import TrajectoryIngestor
from .schema import SpanKind, SpanStatus, TraceRun, TraceSpan

log = get_logger("hook")

# Hook events that mark the end of a session and should trigger finalization.
_FINAL_EVENTS = {"Stop", "SessionEnd"}


def captures_dir(home: Path) -> Path:
    d = home / "captures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def capture_path(home: Path, session_id: str) -> Path:
    safe = session_id.replace("/", "_") or "unknown_session"
    return captures_dir(home) / f"{safe}.jsonl"


def append_event(home: Path, session_id: str, event: dict[str, Any]) -> None:
    """Append one hook payload to the session capture log with a receive time."""
    record = dict(event)
    record.setdefault("_received_at", to_iso(utcnow()))
    path = capture_path(home, session_id)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _read_capture_log(home: Path, session_id: str) -> list[dict[str, Any]]:
    path = capture_path(home, session_id)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def build_run_from_hook_log(events: list[dict[str, Any]], *, session_id: str) -> TraceRun:
    """Build a trajectory from accumulated hook payloads.

    This is the fallback path used when no transcript file is available. It turns
    each prompt submission into a USER span and each completed tool use into a TOOL
    span, inferring app references from the tool input.
    """
    run = TraceRun(agent="claude_code", group_id=session_id, workflow_name="operational_assistant")
    root = run.add_span(TraceSpan(kind=SpanKind.AGENT, name="claude_code_session"))

    first_ts = None
    last_ts = None
    for ev in events:
        name = ev.get("hook_event_name")
        ts_raw = ev.get("_received_at")
        from ..timeutil import from_iso

        ts = from_iso(ts_raw) if ts_raw else None
        if ts:
            first_ts = first_ts or ts
            last_ts = ts
        if name == "UserPromptSubmit":
            run.add_span(TraceSpan(
                kind=SpanKind.USER, name="user_message", parent_id=root.span_id,
                input=ev.get("prompt", ""), started_at=ts,
            ))
        elif name == "PostToolUse":
            tool_name = ev.get("tool_name", "tool")
            args = ev.get("tool_input", {}) or {}
            run.add_span(TraceSpan(
                kind=SpanKind.TOOL, name=tool_name, tool_name=tool_name, tool_args=args,
                parent_id=root.span_id, input=args, output=ev.get("tool_response"),
                started_at=ts, ended_at=ts,
                status=SpanStatus.OK,
                app_refs=infer_app_refs(tool_name, args),
            ))
    run.started_at = first_ts
    run.ended_at = last_ts
    return run


def finalize_session(home: Path, session_id: str, transcript_path: str | None) -> str | None:
    """Build and ingest the trajectory for a finished session.

    Prefers the transcript file when present, otherwise reconstructs from the hook
    capture log. Returns the ingested ``trace_id`` or ``None`` if nothing captured.
    """
    config = load_config()
    config.home = home
    store = open_store(config)
    try:
        run: TraceRun | None = None
        if transcript_path and Path(transcript_path).exists():
            try:
                run = from_claude_code_session(Path(transcript_path), group_id=session_id)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("transcript parse failed, falling back to hook log: %s", exc)
        if run is None or not run.spans:
            events = _read_capture_log(home, session_id)
            if not events:
                return None
            run = build_run_from_hook_log(events, session_id=session_id)
        # A run carrying only its root AGENT span has no substance worth storing,
        # for example a session that ended without any prompt or tool activity.
        if not _has_content(run):
            return None
        ingestor = TrajectoryIngestor(store)
        return ingestor.ingest(run)
    finally:
        store.close()


def _has_content(run: TraceRun) -> bool:
    """True if the run has any span beyond a lone root AGENT span."""
    meaningful = [s for s in run.spans if s.kind != SpanKind.AGENT]
    return bool(meaningful)


def handle(payload: dict[str, Any]) -> dict[str, Any]:
    """Process one hook payload. Returns a small result dict for stdout.

    This is the testable core. The module ``main`` wraps it with stdin and stdout
    handling and guarantees a non blocking exit.
    """
    config = load_config()
    home = config.home
    session_id = str(payload.get("session_id", "unknown"))
    event_name = payload.get("hook_event_name", "")

    # Always record the raw event for the incremental path.
    append_event(home, session_id, payload)

    result: dict[str, Any] = {"captured": event_name, "session_id": session_id}
    if event_name in _FINAL_EVENTS:
        trace_id = finalize_session(home, session_id, payload.get("transcript_path"))
        result["finalized"] = trace_id
    return result


def main(argv: list[str] | None = None) -> int:
    """Read a hook payload from stdin, process it, and exit non blocking."""
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("could not parse hook stdin: %s", exc)
        return 0
    try:
        result = handle(payload)
        # Hooks communicate via stdout; keep it compact and non directive.
        sys.stdout.write(json.dumps(result))
    except Exception as exc:  # pragma: no cover - capture must never block work
        log.warning("hook capture error: %s", exc)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
