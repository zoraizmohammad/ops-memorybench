# Handoff and Status Tracker

Living status for the build. Update this after every commit. Read this plus `plan.md` to resume.

## Current state

- COMPLETE. All nine phases done. All six prompt tasks plus all twelve extensions built, documented, tested, and verified.
- Deliverables: README (diagram, concrete example, honest results table), docs/ set, demo script + captured example, notebooks, docker-compose for the production swap, Claude Code capture plugin.
- An adversarial code review found and confirmed 15 correctness bugs, all fixed with regression tests. The most important was a measurement integrity issue: the headline now compares the outcome grounded score (task outcome + action validity), not the four axis total whose memory axes are zero for the without condition by construction.
- A second independent audit verified every prompt criterion against the running code (see the checklist below). It moved two scalability over-claims to real implementations (Postgres backend, Gmail wired) and surfaced the genuine remaining gaps recorded below.
- Honest headline result (keyless, deterministic): mean outcome score 0.38 to 1.0, success 7 percent to 100 percent, win rate 0.93 (14 of 15 tasks improve, 1 neutral, none regress), Wilcoxon p around 0.001 (0.0002 with SciPy).
- 407 tests passing. Clean clone installs, all tests pass, omb demo runs keyless. Lint clean.
- Branch: main, all work pushed.
- Remote: https://github.com/zoraizmohammad/ops-memorybench.git
- Author identity confirmed: Mohammad Zoraiz <zoraizmohammad@gmail.com>

## Prompt criteria checklist (audited against the running code)

Every requirement below was checked by reading the code and running it, not on faith.

### Task 1 Trajectory capture — COMPLETE
- [x] Claude Code plugin records trajectories (plugin/ombench-capture, 5 hooks, non blocking)
- [x] Team's own trajectory format (TraceRun/TraceSpan in traces/schema.py)
- [x] Agent agnostic (Claude Code and Codex converters emit the identical type; proven by test)
- [x] Runs alongside a real agent (live transcript + incremental hook log)
- [x] Logs what is useful for both KB building and backtesting (app_refs, candidates, corrections)

### Task 2 State snapshots — COMPLETE
- [x] Sync job downloads and stores an app as of time T (omb sync run)
- [x] Universal format across apps (one AppEvent algebra for slack/gcal/gdocs/gmail)
- [x] Stored efficiently (content addressed blobs, dedup, blob/metadata split, integrity verified)
- [x] Multiple apps as POC (Slack, Calendar, Docs, plus Gmail)
- [x] Reconstruct state as of any past T (verified: 9am before reschedule, 3pm after; Docs draft to ready)

### Task 3 Knowledge base pipeline — COMPLETE
- [x] Pipeline turns trajectories into the KB (memory/compiler.py, omb memory compile)
- [x] KB is what the agent reads at runtime (retriever mounts it into the system prompt)
- [x] KB is a readable filesystem (people/, norms/, projects/, procedures/, provenance/)
- [x] gstack / Karpathy LLM Wiki style (markdown with frontmatter)
- [x] EXTENSION cold start from existing integration data (omb memory bootstrap)

### Task 4 Good tasks + rubrics — COMPLETE
- [x] the writeup analysis of what tasks test memory and how to filter (the docs set)
- [x] Curated tasks where memory should help (15 tasks in benchmarks/tasks)
- [x] Each task has a rubric (memory_expected + expected_writes + forbidden_actions + four axis judge)
- [x] Reasoning about good vs bad memory tasks (the docs set + each task's why_memory)
- [x] Tasks tied to trajectories via the miner (eval/miner.py)

### Task 5 Simulated environment — COMPLETE
- [x] Fake environment for an integration (replay/sandbox.py + sandbox_api.py)
- [x] Seeded from a step 2 state snapshot (BacktestRunner materializes then seeds)
- [x] Agent acts against it as if real (tool router with reads and writes, frozen clock)

### Task 6 Backtest — COMPLETE
- [x] Runs curated tasks with and without the KB mounted (paired runner)
- [x] Compares against the rubrics (four axis judge, outcome grounded delta)
- [x] Honest headline (outcome score, not the inflated total; one task correctly neutral)

### Cross cutting scalable / production / many apps — SUBSTANTIALLY COMPLETE (see gaps)
- [x] Extensible to new apps via the Integration base + registry (one row to add an app; Gmail proves it)
- [x] Storage swappable for production (real PostgresBackend selectable via OMBENCH_DATABASE_URL)
- [x] Organized as a real package, not one off scripts (src layout, layered subpackages, typed)
- [ ] Production grade runtime plumbing — see Known gaps below

### Outputs — COMPLETE (with one accepted constraint)
- [x] Git repo with README (to be shared with github.com/kevinrgu by adding as collaborator)
- [x] Separate writeup of architectural decisions (the architecture writeup)
- [x] Writeup includes high fidelity designs for parts not fully built (the docs set)
- [~] Writeup not user authored — NOT satisfied; see Known gaps (user directed)
- [x] Sequential timeline with total hours (the timeline)

## Known gaps and why (honest)

These are the items NOT done, each with the reason. Nothing here is a silent omission.

1. **The required architecture writeup and the timeline are authored by the user, outside the repo.** The prompt requires the writeup to be written by the user. Everything needed to write both is in the repo: the docs/ design set, the per task why_memory fields, this checklist, and the commit history.

2. **No continuously running sync worker / scheduler.** `apps/worker/sync_worker.py` has a tested `run_once` and a `run_forever` loop, but no scheduler, backpressure, retry/alerting, or live API credentials exercised in CI. Reason: the end to end loop runs on synthetic fixtures by design so it is keyless and PII free; standing up a real scheduler and live ingestion is operational work beyond a POC and would require live credentials. The correctness hard part (idempotent appends, deterministic ids, per stream cursors) is done.

3. **In process vector index with a hashing embedder.** Retrieval rebuilds an in memory brute force vector index per query and the default embedder is a deterministic feature hashing embedder, not a learned model. Reason: this keeps the keyless path reproducible and dependency free; the `Embedder` interface and the retriever are the seam where a real embeddings provider and a persistent vector store (pgvector/Qdrant) drop in, documented in the docs set.

4. **Blob store is filesystem based, not an object store.** Content addressing, dedup, and integrity are real, but blobs live on local disk. Reason: same local first rationale; an S3 style BlobStore is the remaining storage swap behind the existing interface.

5. **Live LLM backtest not run.** The headline numbers come from the deterministic stub agent and rule based judge. Reason: reproducibility and zero cost/keyless by default; the Anthropic client is implemented and the same protocol runs against it when ANTHROPIC_API_KEY is set, but the live numbers are not committed because they are non deterministic and would need a key.

6. **Live Codex runtime hook.** Trajectory capture runs live for Claude Code (the plugin); Codex is supported at the converter level only. Reason: the PDF requires "Claude Code OR Codex" (one suffices), and Claude Code is the chosen live runtime.

## API integrations available to test (optional, not required)

The whole platform runs keyless. If the user wants to exercise the live paths, these
credentials activate them additively (all documented in .env.example):
- ANTHROPIC_API_KEY — real Claude agent under test and LLM judge in the backtest
- SLACK_BOT_TOKEN (+ signing secret) — real Slack workspace ingestion
- GOOGLE_CREDENTIALS_FILE + GOOGLE_TOKEN_FILE — real Calendar/Docs/Drive ingestion
- OMBENCH_DATABASE_URL — run against a real Postgres instead of SQLite
None are needed to install, test, demo, or backtest.

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
- [x] Phase 3 Snapshots and integrations
- [x] Phase 4 Memory compiler and retrieval
- [x] Phase 5 LLM layer and agent
- [x] Phase 6 Simulated environment
- [x] Phase 7 Eval harness and benchmark
- [x] Phase 8 Extensions
- [x] Phase 9 Docs demo deliverables and polish

## Notes for the next session

- Run `make test` for the keyless test suite.
- Run `omb demo` for the end to end synthetic backtest once Phase 7 lands.
- Nothing in this repo should require network or credentials to pass CI.
