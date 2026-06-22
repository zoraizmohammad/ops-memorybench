# ombench

**Memory and backtesting for operational agents.**

Agents that do operational and admin work over Slack, Google Calendar, Gmail, and
Drive do not get better over time. They repeat mistakes and lack the institutional and
personal context a good human assistant builds up. Most of that context lives in past
interactions and existing tools, and it is not used.

ombench turns operational agent work into **replayable history**, compiles durable
knowledge from that history into an **agent readable knowledge base**, and measures
whether the compiled memory **actually improves** the agent on real historical tasks.

> This project turns operational agent work into replayable history, compiles durable
> knowledge from that history, and measures whether the compiled memory improves
> performance under historical conditions. It solves the measurement problem, not just
> the storage problem.

## Architecture

```
Agent plugin (Claude Code / Codex) --> Trajectory ingestor --\
Slack / Calendar / Docs sync jobs   --> Canonical app events --+--> Append-only bitemporal event log
                                                                      |
                                                                      v
                                                       Content-addressed blob store (SHA-256)
                                                                      |
                                    +---------------------------------+----------------------------+
                                    v                                 v                            v
                          Snapshot materializer              Memory compiler                 analysis / stats
                                    |                                 |
                                    v                                 v
                            Replay sandbox  <-------- mounted KB filesystem
                                    |                                 |
                        run WITHOUT memory                   run WITH memory
                                    \                                 /
                                     \-----> Rubric + judge + stats <-/
```

See [`docs/architecture.md`](docs/architecture.md) for the layer map and the design
rationale.

## A concrete end to end task

> **Reschedule my 1:1 with Bob.**

The calendar snapshot shows the booking, but not that the user *prefers afternoons and
avoids Fridays*. That preference lives in a past interaction, compiled into the
knowledge base as a durable memory item with provenance back to the trajectory it came
from.

- **Without memory**, the agent picks an uninformed default time. The reschedule lands
  at noon. The rubric scores the outcome wrong.
- **With memory**, the agent reads the mounted preference, reschedules to 3pm, and the
  rubric scores the outcome correct, the memory retrieved, the memory applied, and the
  action valid.

The backtest runs both conditions against the **same seeded snapshot** and reports the
paired delta. This single task is the whole platform in miniature: capture, history,
compilation, replay, and measurement.

## Headline result

Running the curated 15 task benchmark, keyless and deterministic, with the
knowledge base mounted versus not:

| metric | without memory | with memory | delta |
|---|---|---|---|
| mean outcome score | 0.378 | 1.0 | **+0.62** |
| success rate | 6.7% | 100% | **+93 points** |

Win rate 0.93 (bootstrap CI [0.8, 1.0]); paired Wilcoxon p = 0.0002. Fourteen of the
fifteen tasks improve with the right memory mounted and none regress; the one neutral
task is a prior decision lookup the agent answers correctly either way.

The headline compares the **outcome grounded score** (task outcome and action
validity), not the full four axis rubric total, because the two memory axes are zero
for the without memory condition by experimental construction and would inflate the
delta. The four axis total is reported per task as a diagnostic. Reproduce it all with
`make demo`.

## Quick start

```bash
make venv
make dev
make test     # the full keyless test suite
make demo      # the end to end with vs without memory backtest
```

Nothing above needs credentials or network access. The whole loop runs on bundled
synthetic fixtures using a deterministic agent and judge.

For a guided walkthrough of every layer as real CLI commands:

```bash
bash scripts/demo.sh
```

## The CLI

```
omb info                 # show configuration and which live paths are enabled
omb trace ingest PATH    # ingest an agent transcript into the history substrate
omb sync run all         # sync Slack, Calendar, Docs into the bitemporal event log
omb snapshot create      # materialize a point in time snapshot
omb saasgit log A T ID   # git for SaaS: version history of an entity
omb saasgit show A T ID --at TIME    # reconstruct an entity as of a past time
omb memory compile       # compile the knowledge base from trajectories and app state
omb memory retrieve Q    # show the memory bundle the agent would receive for a query
omb eval run             # run the paired backtest and print the results table
omb eval mine            # mine candidate benchmark tasks from captured trajectories
omb viz provenance       # render the memory provenance graph as Graphviz DOT
omb viz timetravel A T ID  # walk an entity through its versions over time
omb viz dashboard        # write a self contained HTML backtest dashboard
omb demo                 # the full end to end synthetic backtest
```

## What is here

| Layer | Package | Role |
|---|---|---|
| Trajectory capture | `ombench.traces` | Agent agnostic capture, redaction, OTel interop, Claude Code plugin |
| History substrate | `ombench.events`, `ombench.storage` | Append only bitemporal event log over a content addressed blob store |
| Snapshots | `ombench.snapshots` | Point in time materialization with a merkle root, git for SaaS |
| Memory | `ombench.memory` | Knowledge base compiler and hybrid retrieval |
| Replay | `ombench.replay` | Deterministic simulated SaaS environment |
| Evaluation | `ombench.eval` | Tasks, rubrics, judges, and the paired backtest |
| Integrations | `ombench.integrations` | Slack, Calendar, Docs adapters with synthetic fixtures |
| Visualization | `ombench.viz` | Diff viewer, provenance graph, approval queue, counterfactual explorer, time travel, HTML dashboard |

The platform implements all six prompt tasks and the feasible, stretch, and research
extensions. See [`docs/extensions.md`](docs/extensions.md).

## Going live (optional)

Copy `.env.example` to `.env` and fill in only what you want to activate:

- `ANTHROPIC_API_KEY` swaps the deterministic agent and judge for Claude (Opus 4.8 by
  default, with adaptive thinking).
- Slack and Google credentials swap synthetic fixtures for real workspace ingestion.

Everything is additive. With an empty environment the platform still runs end to end.

## Design highlights

- **Bitemporal history.** Every event carries `valid_at` (when it took effect in the
  source app) and `ingested_at` (when ombench learned it). State is reconstructed as
  `S(T, tau) = fold(S0, { e | valid_at(e) <= T and ingested_at(e) <= tau })`, which
  prevents a backtest from leaking information the agent could not have had. See
  [`docs/bitemporal.md`](docs/bitemporal.md).
- **Content addressed storage.** Payloads are stored by SHA-256 of their canonical
  JSON, giving deduplication, integrity, and cheap snapshots.
- **Compiled, human readable memory.** The knowledge base is a filesystem of markdown
  with provenance, not only a vector index, so it is legible and auditable. See
  [`docs/memory-model.md`](docs/memory-model.md).
- **Self owned Docs snapshots.** The Docs API returns only the latest version, so
  ombench takes its own immutable content snapshots at sync time and stores them
  content addressed, which is what makes historical Docs replay faithful.
- **Counterfactual replay.** The same task runs against the same seeded snapshot with
  memory disabled and enabled, scored on a four axis rubric with bootstrap confidence
  intervals and a paired significance test. See [`docs/eval-protocol.md`](docs/eval-protocol.md).

## Project documents

- the writeup architectural decisions and tradeoffs, with designs for
  parts left as future work.
- the timeline a sequential record of the build with hours.
- [`docs/`](docs/) the design documentation set.
- [`plan.md`](plan.md) the full execution plan; [`handoff.md`](handoff.md) the status tracker.

## License

MIT. See [LICENSE](LICENSE).
