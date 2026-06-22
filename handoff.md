# Handoff and Status Tracker

Living status for the build. Update this after every commit. Read this plus `plan.md` to resume.

## Current state

- Phase: 3 (Snapshots and integrations) — starting
- Last commit: 818ebc4 Add Claude Code plugin hook capture entrypoint and docs
- Phase 0 complete: scaffold, pyproject, config/ids/timeutil/logging, CI, Makefile, README, CLI
- Phase 1 complete: blob store, storage backend + SQLite + migrations, AppEvent algebra, bitemporal EventStore with fold, query helpers
- Phase 2 complete (Task 1): trajectory schema, redaction, ingest, OTel/OpenInference adapter, Claude Code + Codex converters, Claude Code plugin hook capture, omb trace CLI. Verified end to end.
- 132 tests passing total.
- Branch: main
- Discipline note: always run `.venv/bin/python -m ruff check src tests` and `pytest -q` before committing.
- Remote: https://github.com/zoraizmohammad/ops-memorybench.git
- Author identity confirmed: Mohammad Zoraiz <zoraizmohammad@gmail.com>

## Locked decisions

- Integration data: synthetic fixtures + production-shaped real adapters (keyless by default).
- LLM: pluggable, primary Anthropic Claude, deterministic stub fallback. No key required to run.
- Storage: local-first SQLite + filesystem blob store + DuckDB analysis, behind StorageBackend.
- Writeup and timeline: authored by the user, outside the repo, because the prompt requires the writeup be written by the user.
- Build all feasible and stretch extensions; research extensions where they strengthen platform.
- Package name: ombench. CLI console script: omb.

## API access status

None required. All optional and additive:
- ANTHROPIC_API_KEY (live agent + judge) — not yet provided, stub active.
- Slack bot token + signing secret — not yet provided, synthetic fixtures active.
- Google OAuth (Calendar/Drive/Docs read-only) — not yet provided, synthetic fixtures active.

## Commit conventions (must follow)

- Sole author Mohammad Zoraiz, no co-author trailers.
- No colon and no em or en dashes in commit titles or descriptions.
- One commit per completed step, build and test first, push after.

## Progress checklist

See `plan.md` section 6 for the full commit list. Mark each here as it lands.

- [x] Phase 0 Foundation
- [x] Phase 1 Event store and blob store
- [x] Phase 2 Trajectory capture
- [ ] Phase 3 Snapshots and integrations
- [ ] Phase 4 Memory compiler and retrieval
- [ ] Phase 5 LLM layer and agent
- [ ] Phase 6 Simulated environment
- [ ] Phase 7 Eval harness and benchmark
- [ ] Phase 8 Extensions
- [ ] Phase 9 Docs demo deliverables and polish

## Notes for the next session

- Run `make test` for the keyless test suite.
- Run `omb demo` for the end to end synthetic backtest once Phase 7 lands.
- Nothing in this repo should require network or credentials to pass CI.
