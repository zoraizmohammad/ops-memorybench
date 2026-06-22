# Execution Plan — Memory and Backtesting for Operational Agents

This is the authoritative, exact execution plan for building the full platform described in
the take-home prompt (`memagent.pdf`). It is written to be **resumable**: any session can read
this file plus `handoff.md` and continue without losing context. `handoff.md` is the living
status tracker; this file is the stable plan.

The standard for this project is a **complete, reusable, team-buildable platform**, not a toy
demo. Every component is built for real, with tests and documentation. Parts the prompt allows
to be "written up instead of built" are still built here wherever feasible, and documented
thoroughly besides.

---

## 1. Mission and success criteria

Build a reusable systems substrate that does four things at once:

1. **Agent-agnostic trajectory capture** from a running agent (Claude Code / Codex).
2. **Point-in-time reconstruction of SaaS state** ("git for SaaS"), across apps, stored efficiently.
3. **A knowledge-base compiler** that turns trajectories and existing app data into an
   agent-readable knowledge base mounted back into the agent at runtime.
4. **A replay/backtest harness** that measures, with statistics, whether the knowledge base
   improves the agent on real historical operational tasks.

Integrations for the proof of concept: **Slack + Google Calendar + Google Docs** (Gmail is a
documented future path).

### Definition of done

- [ ] All six prompt tasks implemented (not just written up), end to end.
- [ ] All "feasible" and "stretch" extensions implemented. Research-tier extensions implemented
      where they round out the platform.
- [ ] Whole loop runs **keyless** (synthetic fixtures + deterministic stub) via one command.
- [ ] Live paths (Anthropic LLM, real Slack/Google) activate when credentials are present.
- [ ] Unit + integration + replay tests pass in CI. Coverage on core substrate.
- [ ] Three deliverables produced: `README.md`, the architecture writeup (architecture decisions),
      the timeline (sequential timeline with total hours).
- [ ] Every meaningful step committed (sole author Mohammad Zoraiz) and pushed. Commit titles
      and descriptions contain no colon `:` and no em/en dashes.

---

## 2. Prompt task to component mapping

| Prompt task | Component(s) | Status |
|---|---|---|
| 1. Trajectory capture | `traces/` schema, ingest, redact, OTel/OpenInference adapter, Claude Code plugin | planned |
| 2. State snapshots | `events/` bitemporal log, `storage/blobstore` content addressing, `snapshots/` materializer, `integrations/{slack,gcal,gdocs}` | planned |
| 3. Knowledge base pipeline | `memory/` extractor, scorer, resolver, compiler, KB filesystem, retriever, router; cold-start bootstrap | planned |
| 4. Good tasks + rubrics (writeup + curation) | `eval/tasks`, `eval/rubrics`, task miner, 15 curated benchmark tasks, the docs set | planned |
| 5. Simulated environment | `replay/` sandbox, contracts, validators, frozen clock; per-app `sandbox_api` | planned |
| 6. Backtest | `eval/runner`, `eval/judges`, `eval/stats`, `eval/reports` | planned |

---

## 3. Architecture

The canonical history is an **append-only bitemporal event log**. Snapshots are acceleration
structures. The compiled KB is the runtime interface the agent reads. The replay harness proves
causal value.

Central state equation:

```
S(T, tau) = fold(S0, { e | valid_at(e) <= T and ingested_at(e) <= tau })
```

`valid_at` is when the event took effect in the source system; `ingested_at` is when our
platform learned it. Bitemporal modeling lets us reconstruct both "state as of T" and "state as
of T using only what had been ingested by time tau" which is exactly what honest backtesting
requires (no leakage of information the agent could not have had).

```
Agent plugin (Claude Code / Codex) --> Trajectory ingestor --\
Slack / Calendar / Docs sync jobs   --> Canonical app events --+--> Append-only bitemporal event log
                                                                      |
                                                                      v
                                                       Content-addressed blob store (SHA-256)
                                                                      |
                                    +---------------------------------+----------------------------+
                                    v                                 v                            v
                          Snapshot materializer              Memory compiler               (analysis / DuckDB)
                                    |                                 |
                                    v                                 v
                            Replay sandbox  <-------- mounted KB filesystem
                                    |                                 |
                        run WITHOUT memory                   run WITH memory
                                    \                                 /
                                     \-----> Rubric + judge + stats <-/
```

### Core abstractions

| Abstraction | Purpose | Minimal fields |
|---|---|---|
| `TraceRun` | One end-to-end agent job | `trace_id, group_id, workflow_name, started_at, ended_at, user_ref, task_ref` |
| `TraceSpan` | One operation within a run | `span_id, parent_id, kind, input_ref, output_ref, tool_ref, app_refs, status, cost, tokens` |
| `AppEvent` | Canonical normalized app mutation/observation | `event_id, app, entity_type, entity_id, op, payload_hash, valid_at, ingested_at, source_cursor, provenance` |
| `SnapshotManifest` | Materialized point-in-time state root | `snapshot_id, app, as_of_valid_time, as_of_ingest_time, root_hash` |
| `MemoryItem` | Durable compiled knowledge unit | `memory_id, type, namespace, subject_refs, claim, evidence_refs, confidence, ttl_policy, acl` |
| `TaskSpec` | Replayable benchmark task | `task_id, snapshot_ref, prompt, expected_state_assertions, memory_expected_refs, rubric_id` |
| `ReplayResult` | One evaluated run | `task_id, condition, trace_id, retrieved_memory_refs, actions, scores, latency, cost` |

---

## 4. Technology decisions (locked)

| Decision | Choice | Rationale |
|---|---|---|
| Integration data | Synthetic fixtures + production-shaped real adapters | Whole loop runs keyless and PII-free; adapters still honor real API contracts and accept live creds |
| LLM | Pluggable layer, primary Anthropic Claude, deterministic stub fallback | Live runs use real model; CI and demos run reproducibly with no key |
| Storage | Local-first SQLite + filesystem blob store + DuckDB analysis, behind `StorageBackend` interface | Zero infra, fully demonstrates bitemporal + content addressing, swappable to Postgres/pgvector |
| Writeup | Authored by the user, outside the repo | The prompt requires the writeup be written by the user; the docs/ set holds the rationale to write from |
| Language | Python 3.11+, `src/` layout, package `ombench` | Reusable, importable, pip-installable |
| Vector index | Start in-process (numpy) behind embedder interface | Minimize moving parts; Qdrant/pgvector path documented |
| CLI | `omb` console script (Typer) | SaaS Git CLI + memory/replay/eval tooling |

Optional credentials (additive, never required):
`ANTHROPIC_API_KEY`; Slack bot token + signing secret; Google OAuth (Calendar/Drive/Docs read-only).

---

## 5. Repository layout (target)

```
ops-memorybench/
  README.md  the architecture writeup  the timeline  plan.md  handoff.md
  pyproject.toml  LICENSE  .gitignore  .env.example  Makefile  docker-compose.yml
  .github/workflows/ci.yml

  src/ombench/
    config.py  ids.py  timeutil.py  logging.py
    storage/   backend.py sqlite_backend.py blobstore.py migrations/
    traces/    schema.py ingest.py redact.py otel_adapter.py converters.py
    events/    schema.py bitemporal.py store.py algebra.py merge.py
    snapshots/ materialize.py manifest.py diff.py hashstore.py
    memory/    candidate_extractor.py scorer.py resolver.py compiler.py kb.py
               router.py retriever.py embeddings.py bm25.py graph.py budget.py
               predictor.py procedure_synth.py
    replay/    sandbox.py contracts.py validators.py clock.py faults.py
    eval/      tasks.py rubrics.py judges.py runner.py stats.py reports.py miner.py
    llm/       base.py anthropic_client.py stub.py agent.py
    integrations/ base.py slack/ gcal/ gdocs/ gmail/
    cli/       main.py saasgit.py memcmds.py replaycmds.py evalcmds.py
    apps/      worker/sync_worker.py replay/replay_runner.py
    viz/       memory_diff.py provenance.py approval_queue.py timetravel.py
               counterfactual.py report_html.py

  kb_templates/ people/ projects/ workflows/ norms/ procedures/
  fixtures/     slack/ gcal/ gdocs/ trajectories/
  benchmarks/   tasks/
  notebooks/    benchmark_mining.ipynb error_analysis.ipynb
  docs/         architecture.md bitemporal.md trajectory-format.md memory-model.md
                eval-protocol.md extensions.md
  tests/        unit/ integration/ replay/ conftest.py
```

---

## 6. Phased execution plan (commit-sized steps)

Each line is intended to be one commit. Build + test before each commit. Push after each commit
(or in small batches if the remote rate-limits). Commit titles/descriptions: no `:`, no dashes.

### Phase 0 — Foundation and scaffold
- C0.1 Add execution plan and handoff tracker
- C0.2 Add gitignore env example pyproject and package skeleton
- C0.3 Add config ids timeutil and logging modules with tests
- C0.4 Add CI workflow Makefile and README skeleton

### Phase 1 — Bitemporal event store and content addressed blob store
- C1.1 Add content addressed blob store with sha256 and tests
- C1.2 Add storage backend interface and SQLite backend with migrations
- C1.3 Add AppEvent schema and canonical operation algebra
- C1.4 Add append only bitemporal event log with fold materialization and tests
- C1.5 Add event store query helpers and integration tests

### Phase 2 — Trajectory capture (Task 1)
- C2.1 Add agent agnostic trajectory schema for runs and spans
- C2.2 Add trajectory ingest pipeline with redaction and tests
- C2.3 Add OpenTelemetry and OpenInference adapter mapping
- C2.4 Add Claude Code and Codex session converters
- C2.5 Add Claude Code plugin hook capture entrypoint and docs

### Phase 3 — Snapshots and integrations (Task 2)
- C3.1 Add integration base interfaces for sync normalize and sandbox
- C3.2 Add Slack sync adapter and normalizer honoring Events API contracts
- C3.3 Add Slack synthetic fixtures and sync tests
- C3.4 Add Google Calendar sync adapter with sync token and 410 handling
- C3.5 Add Calendar synthetic fixtures and tests
- C3.6 Add Google Docs and Drive sync adapter with export snapshots
- C3.7 Add Docs synthetic fixtures and tests
- C3.8 Add snapshot materializer manifest merkle root and diff
- C3.9 Add snapshot CLI commands and end to end snapshot tests
- C3.10 Add Gmail future path adapter stub and design notes

### Phase 4 — Memory compiler and retrieval (Task 3)
- C4.1 Add memory item schema and KB filesystem read write with frontmatter
- C4.2 Add candidate extractor for episodic semantic and procedural memory
- C4.3 Add scorer with utility and confidence models and tests
- C4.4 Add contradiction resolver with supersede edges and tests
- C4.5 Add KB compiler producing readable files with provenance
- C4.6 Add BM25 lexical index
- C4.7 Add pluggable embeddings with deterministic fallback
- C4.8 Add hybrid retriever with reciprocal rank fusion graph expand and rerank
- C4.9 Add namespace router
- C4.10 Add cold start bootstrap from integration data
- C4.11 Add memory CLI compile show diff and provenance

### Phase 5 — LLM layer and agent under test
- C5.1 Add LLM client interface and deterministic stub
- C5.2 Add Anthropic client behind the interface
- C5.3 Add operational agent under test with tool loop
- C5.4 Add agent tests against the stub

### Phase 6 — Simulated environment (Task 5)
- C6.1 Add sandbox base with frozen clock and sandbox event log
- C6.2 Add Slack sandbox API seeded from a snapshot
- C6.3 Add Calendar sandbox API seeded from a snapshot
- C6.4 Add Docs sandbox API seeded from a snapshot
- C6.5 Add trace contracts and state diff validators
- C6.6 Add fault injection for replay contracts
- C6.7 Add sandbox tests

### Phase 7 — Eval harness backtest and benchmark tasks (Tasks 4 and 6)
- C7.1 Add task spec schema and loader
- C7.2 Add four axis rubric model
- C7.3 Add rule based judge and Anthropic judge with bias safeguards
- C7.4 Add paired backtest runner for with and without memory
- C7.5 Add statistics bootstrap confidence intervals Wilcoxon and Cohen kappa
- C7.6 Add report generator for markdown and html
- C7.7 Add task miner from trajectories
- C7.8 Add fifteen curated benchmark task specs and fixtures
- C7.9 Add eval CLI and end to end backtest test

### Phase 8 — Extensions (feasible plus stretch plus research)
- C8.1 Add SaaS Git CLI with checkout log diff and show
- C8.2 Add memory diff viewer
- C8.3 Add provenance graph viewer
- C8.4 Add human approval queue
- C8.5 Add prompt time memory budget optimizer
- C8.6 Add counterfactual replay explorer
- C8.7 Add memory usefulness predictor
- C8.8 Add procedure synthesizer
- C8.9 Add time travel debugging UI
- C8.10 Add learned namespace router variant
- C8.11 Add HTML report dashboard

### Phase 9 — Docs demo deliverables and polish
- C9.1 Add architecture documentation set
- C9.2 Add end to end demo script and example run
- C9.3 Add README with diagram example and results table
- C9.4 Add the writeup with architecture decisions
- C9.5 Add the timeline with hours
- C9.6 Add notebooks for benchmark mining and error analysis
- C9.7 Final comprehensive review pass and fixes

---

## 7. Extensions plan

Feasible (all built): SaaS Git CLI, memory diff viewer, provenance graph, human approval queue,
task miner from traces, prompt-time memory budget optimizer.

Stretch (all built): counterfactual replay explorer, memory usefulness predictor, procedure
synthesizer, time-travel debugging UI.

Research (built where they strengthen the platform): learned namespace router, fault-injected
replay contracts.

---

## 8. Testing strategy

- **Unit tests** for every core module (blob store, bitemporal fold, algebra, scorer, resolver,
  retriever fusion, stats).
- **Integration tests** for sync -> event log -> snapshot -> KB compile.
- **Replay tests** for sandbox determinism and the full paired backtest on synthetic fixtures.
- **Property tests** for content addressing (same payload -> same hash; order independence of
  snapshot root).
- CI runs the keyless path on every push.

---

## 9. Deliverables

1. `README.md` leading with architecture diagram, one concrete end-to-end task, and a paired
   with-memory vs without-memory results table.
2. the architecture writeup detailing architectural decisions and tradeoffs, with thorough designs for any
   parts not fully built.
3. the timeline with a sequential record of work and total hours.

---

## 10. Git and commit conventions

- Sole author Mohammad Zoraiz, email zoraizmohammad@gmail.com (already configured).
- No co-author trailers.
- Commit titles and descriptions contain no colon and no em or en dashes.
- One commit per completed step. Build and test before committing. Push after each commit.
- `memagent.pdf` and `memagentguidelines.md` are gitignored (original prompt and private
  research are not published).

---

## 11. Risks and open questions

- **Google Docs historical replay**: the Docs API returns only the latest version, so we take
  our own immutable content snapshots (exported markdown/blocks) and store them content-addressed.
  This is the documented correct approach and is implemented here.
- **Slack history limits**: real backfill depends on scopes and membership; synthetic fixtures
  remove this constraint for the POC while adapters honor the real contract.
- **LLM stochasticity**: judge is rubric- and evidence-grounded and blind to condition order;
  stub path is fully deterministic; live path supports repeated runs per condition.
