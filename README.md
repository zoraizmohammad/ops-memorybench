# ombench

**Memory and backtesting for operational agents.**

Agents that do operational and admin work over Slack, Google Calendar, Gmail, and
Drive do not get better over time. They repeat mistakes and lack the institutional
and personal context a good human assistant builds up. Most of that context lives in
past interactions and existing tools, and it is not used.

ombench turns operational agent work into **replayable history**, compiles durable
knowledge from that history into an **agent readable knowledge base**, and measures
whether the compiled memory **actually improves** the agent on real historical tasks.

> The core idea: SaaS apps have no git, so to backtest an agent you must reconstruct
> the state of each app at the point in time a task happened. ombench is that history
> substrate, plus a knowledge base compiler, plus a counterfactual replay harness.

This README is a skeleton that is filled in as the platform is built. See
[`plan.md`](plan.md) for the full execution plan and [`handoff.md`](handoff.md) for
current status.

## What is here

| Layer | Package | Role |
|---|---|---|
| Trajectory capture | `ombench.traces` | Agent agnostic capture of agent and user trajectories |
| History substrate | `ombench.events`, `ombench.storage` | Append only bitemporal event log over a content addressed blob store |
| Snapshots | `ombench.snapshots` | Point in time materialization, git for SaaS |
| Memory | `ombench.memory` | Knowledge base compiler and hybrid retrieval |
| Replay | `ombench.replay` | Deterministic simulated SaaS environment |
| Evaluation | `ombench.eval` | Tasks, rubrics, judges, and the paired backtest |
| Integrations | `ombench.integrations` | Slack, Calendar, Docs adapters with synthetic fixtures |

## Quick start

```bash
make venv
make dev
make test     # runs the full keyless loop on synthetic fixtures
make demo      # end to end with vs without memory backtest (coming in Phase 7)
```

Nothing above requires credentials or network access. The whole loop runs on bundled
synthetic fixtures using a deterministic agent and judge.

## Going live (optional)

Copy `.env.example` to `.env` and fill in only what you want to activate:

- `ANTHROPIC_API_KEY` swaps the deterministic agent and judge for Claude.
- Slack and Google credentials swap synthetic fixtures for real workspace ingestion.

Everything is additive. With an empty environment the platform still runs end to end.

## Design highlights

- **Bitemporal history.** Every event carries both `valid_at` (when it took effect in
  the source app) and `ingested_at` (when ombench learned it). State is reconstructed
  as `S(T, tau) = fold(S0, { e | valid_at(e) <= T and ingested_at(e) <= tau })`, which
  prevents a backtest from leaking information the agent could not have had.
- **Content addressed storage.** Payloads are stored by SHA-256 of their canonical
  JSON, in the spirit of Git objects and IPFS, giving deduplication, integrity, and
  cheap snapshots.
- **Compiled, human readable memory.** The knowledge base is a filesystem of markdown
  with provenance, not only a vector index, so it is legible and auditable.
- **Counterfactual replay.** The same task runs against the same seeded snapshot with
  memory disabled and enabled, scored on a four axis rubric with bootstrap confidence
  intervals and a paired significance test.

## License

MIT. See [LICENSE](LICENSE).
