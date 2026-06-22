# Architecture

ombench is centered on a **history engine**, not on any single agent or app. The
layers mirror the data flow from capture to measurement, and each is a clean
abstraction the others build on.

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

## Layer map

| Layer | Package | Responsibility |
|---|---|---|
| Storage | `ombench.storage` | Content addressed blob store and a swappable relational backend |
| Events | `ombench.events` | Canonical append only bitemporal `AppEvent` log with fold materialization |
| Traces | `ombench.traces` | Agent agnostic trajectory capture, redaction, OTel interop, converters, hook |
| Integrations | `ombench.integrations` | Slack, Calendar, Docs sync adapters and synthetic fixtures |
| Snapshots | `ombench.snapshots` | Point in time state materialization with a merkle root and diffs |
| Memory | `ombench.memory` | Candidate extraction, scoring, contradiction resolution, KB compilation, hybrid retrieval |
| LLM | `ombench.llm` | Pluggable client (Anthropic + deterministic stub) and the agent under test |
| Replay | `ombench.replay` | Deterministic sandbox, tool router, validators, fault injection |
| Eval | `ombench.eval` | Tasks, rubrics, judges, paired backtest runner, statistics, reports, task miner |
| Viz | `ombench.viz` | Diff viewer, provenance graph, approval queue, counterfactual explorer, time travel, HTML dashboard |

## Why this decomposition

The decomposition is a direct consequence of two facts that the SaaS APIs force on us:

1. **Event feeds and history methods are not the same thing.** A Slack event stream
   and `conversations.history`, a Calendar `syncToken` feed, and a Docs export are
   structurally different acquisition modes. Normalizing them all into one canonical
   event algebra is what makes the history engine universal.

2. **Historical state and runtime memory are not the same thing.** The snapshot
   materializer answers "what was the app state at time T"; the memory compiler
   answers "what durable knowledge should the agent carry". Replay and evaluation sit
   on top of both.

See `bitemporal.md` for the state model, `memory-model.md` for the knowledge base
design, and `eval-protocol.md` for the backtest protocol.
