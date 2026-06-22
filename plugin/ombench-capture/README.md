# ombench-capture

A Claude Code plugin that records agent trajectories into the
[ombench](https://github.com/zoraizmohammad/ops-memorybench) history substrate.

It runs alongside Claude Code doing real operational work and logs whatever is
useful for two purposes: building a knowledge base and backtesting. Capture is
agent agnostic; the same trajectory format is produced by the Codex converter.

## What it captures

The plugin registers command hooks on five events. Each invocation runs
`python3 -m ombench.traces.hook`, which reads the hook payload from stdin:

| Event | Captured |
|---|---|
| `UserPromptSubmit` | The user's prompt, as a USER span |
| `PreToolUse` | The tool name and input, recorded for reconciliation |
| `PostToolUse` | The tool name, input, and response, as a TOOL span with inferred app refs |
| `Stop` | Finalizes the turn, building and ingesting the trajectory |
| `SessionEnd` | Finalizes the session |

On finalization the hook prefers the full Claude Code transcript (`transcript_path`)
and falls back to the incremental hook capture log. Payloads are redacted before
storage and large values are offloaded to the content addressed blob store.

The hook is non blocking by design. It always exits 0 and never interrupts the
agent, because a capture failure must not disrupt real work.

## Install

1. Install ombench so the module is importable on the same Python that runs the hook:

   ```bash
   pip install -e /path/to/ops-memorybench
   ```

2. Point Claude Code at this plugin. Either enable it as a plugin, or copy the hook
   configuration in `hooks/hooks.json` into your `~/.claude/settings.json` or a
   project `.claude/settings.json`.

3. Optionally set `OMBENCH_HOME` to choose where trajectories are stored. It
   defaults to `.ombench` in the working directory.

## Inspect captures

```bash
omb trace list             # list captured runs
omb trace show <trace_id>  # show one trajectory
```
