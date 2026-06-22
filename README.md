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

---

## Table of contents

- [Architecture](#architecture)
- [A concrete end to end task](#a-concrete-end-to-end-task)
- [Headline result](#headline-result)
- [Install](#install)
- [Quick start](#quick-start)
- [The CLI, command by command](#the-cli-command-by-command)
- [How it works, layer by layer](#how-it-works-layer-by-layer)
- [The paired backtest](#the-paired-backtest)
- [Extending the platform](#extending-the-platform)
- [Going to production](#going-to-production)
- [Going live with real credentials](#going-live-with-real-credentials)
- [Repository layout](#repository-layout)
- [Testing](#testing)
- [Project documents](#project-documents)

---

## Architecture

ombench is centered on a **history engine**, not on any single agent or app. The
layers run from capture, through a bitemporal history substrate, to a compiled
knowledge base, to a deterministic replay that proves causal value.

![architecture](docs/diagrams/architecture.svg)

The packages depend strictly downward: each layer uses only the layers below it. This
is what keeps the platform a real system rather than a pile of scripts.

![layers](docs/diagrams/layers.svg)

> The diagrams above are committed SVGs rendered from the PlantUML sources in
> [`docs/diagrams/`](docs/diagrams/) (regenerate with `make diagrams`). The design
> rationale behind this decomposition is in [`docs/architecture.md`](docs/architecture.md).

---

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
compilation, replay, and measurement. You can watch each step run as real commands:

```bash
bash scripts/demo.sh
```

---

## Headline result

Running the curated 15 task benchmark, keyless and deterministic, with the knowledge
base mounted versus not:

| metric | without memory | with memory | delta |
|---|---|---|---|
| mean outcome score | 0.378 | 1.0 | **+0.62** |
| success rate | 6.7% | 100% | **+93 points** |

Win rate 0.93 (bootstrap CI [0.8, 1.0]); paired Wilcoxon p around 0.001 (the keyless
default uses a pure Python normal approximation; with SciPy installed it is 0.0002).
Fourteen of the fifteen tasks improve with the right memory mounted and none regress;
the one neutral task is a prior decision lookup the agent answers correctly either way.

The headline compares the **outcome grounded score** (task outcome and action
validity), not the full four axis rubric total, because the two memory axes are zero
for the without memory condition by experimental construction and would inflate the
delta. The four axis total is reported per task as a diagnostic. Reproduce it all with
`make demo`.

---

## Install

Requires Python 3.11 or newer. No credentials, no services, no network.

```bash
git clone https://github.com/zoraizmohammad/ops-memorybench
cd ops-memorybench
make venv      # create .venv
make dev       # editable install with dev + stats + analysis extras
```

Or without make:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Optional extras, all additive and none required to run:

| Extra | Enables |
|---|---|
| `ombench[llm]` | the real Anthropic Claude agent and judge |
| `ombench[stats]` | SciPy / statsmodels exact statistics (pure Python fallback otherwise) |
| `ombench[postgres]` | the Postgres production storage backend |
| `ombench[google]`, `ombench[slack]` | real Calendar/Docs/Drive and Slack ingestion |
| `ombench[all]` | everything |

---

## Quick start

```bash
make test      # the full keyless test suite (407 tests)
make demo      # the end to end with vs without memory backtest
```

`make demo` syncs the bundled fixtures, loads a curated knowledge base, runs the paired
backtest over all fifteen tasks, and prints the results table. It needs no credentials
and is fully deterministic.

---

## The CLI command by command

Everything is driven by the `omb` console script. With an empty environment every
command runs keyless against bundled synthetic fixtures.

```bash
omb info                          # show config and which live paths are enabled
```

**Trajectory capture (Task 1).**

```bash
omb trace ingest <path.jsonl>     # ingest a Claude Code or Codex transcript
omb trace ingest <path.json> --agent codex
omb trace list                    # list captured trajectory runs
omb trace show <trace_id>         # show one trajectory as a span tree
```

**State snapshots (Task 2).**

```bash
omb sync run all                  # sync Slack, Calendar, Docs, Gmail into the event log
omb sync run gcal                 # sync one app
omb sync stats                    # summary counts over the bitemporal log
omb snapshot create --label now   # materialize a point in time snapshot
omb snapshot list
omb snapshot diff <id1> <id2>     # diff two snapshots by entity version hash
```

**Git for SaaS (extension).**

```bash
omb saasgit log gcal event ev_1on1_bob              # version history of an entity
omb saasgit show gcal event ev_1on1_bob --at 2026-05-10T00:00:00Z   # reconstruct as of T
omb saasgit diff 2026-05-05T00:00:00Z 2026-06-01T00:00:00Z          # what changed between two T
omb saasgit checkout 2026-06-01T00:00:00Z --label snap              # full snapshot at T
omb saasgit ls --app-name gcal                                       # entities present at T
```

**Knowledge base (Task 3).**

```bash
omb memory bootstrap              # cold start: compile the KB from existing app state
omb memory compile                # compile the KB from captured trajectories + app state
omb memory list                   # list compiled memory items
omb memory show <memory_id>       # show an item with its provenance
omb memory retrieve "what time do I prefer"   # the bundle the agent would receive
```

**Backtest (Tasks 4 + 6).**

```bash
omb eval run                      # paired with vs without memory backtest + results table
omb eval mine                     # mine candidate benchmark tasks from trajectories
```

**Visualization and trust surfaces (extensions).**

```bash
omb viz provenance --out prov.dot                 # memory provenance graph as Graphviz DOT
omb viz timetravel gcal event ev_1on1_bob         # walk an entity through its versions
omb viz dashboard --out backtest.html             # self contained HTML results dashboard
```

**The whole loop.**

```bash
omb demo                          # sync, seed memory, backtest, print results
```

---

## How it works layer by layer

### Trajectory capture (Task 1)

The bundled Claude Code plugin in [`plugin/ombench-capture/`](plugin/ombench-capture/)
registers command hooks on five session events (`UserPromptSubmit`, `PreToolUse`,
`PostToolUse`, `Stop`, `SessionEnd`). Each runs `python -m ombench.traces.hook`, a non
blocking entrypoint that accumulates the session and, on session end, builds a
trajectory preferring the full transcript and falling back to the incremental hook log.

Trajectories use the platform's own span based format (`ombench.traces.schema`), aligned
to OpenTelemetry and OpenInference so it interoperates with existing observability
stacks. It is **agent agnostic**: the Claude Code and Codex converters both produce the
identical `TraceRun` type, and no downstream code branches on which agent produced it.
Payloads are redacted before storage and large values are offloaded to the content
addressed blob store.

### History substrate: the bitemporal event log (Task 2)

Every integration normalizes its raw API shapes into one canonical `AppEvent` algebra,
so the history engine is universal across apps rather than a per app script. Events are
**append only** and carry two times: `valid_at` (when the change took effect in the
source app) and `ingested_at` (when ombench learned it). State is a deterministic fold:

```
S(T, tau) = fold(S0, { e | valid_at(e) <= T and ingested_at(e) <= tau })
```

The two time axes are what make a backtest honest. A single event time would leak a
late arriving backfill into a replay, inflating what the agent appeared to know at the
time:

![bitemporal](docs/diagrams/bitemporal.svg)

Payloads are stored by SHA-256 of their canonical JSON in a git style content addressed
blob store, giving deduplication, integrity, and cheap snapshots. A `SnapshotManifest`
is a Merkle style root over entity version hashes, the SaaS analogue of a git commit.

**Google Docs** is the hard case: its API returns only the latest version. ombench
takes its own immutable content snapshots at sync time and stores them content
addressed, so historical Docs content is reconstructable, which the Docs API alone
cannot do. See [`docs/bitemporal.md`](docs/bitemporal.md).

### Knowledge base compiler and retrieval (Task 3)

History is compiled into a readable knowledge base filesystem (markdown with YAML
frontmatter and JSON provenance) under `people/`, `projects/`, `norms/`, `procedures/`,
`timeline/`. The pipeline extracts candidates, scores them with an evidence based
logistic confidence model, deduplicates and persists them **append only**, resolves
contradictions with supersede edges, and writes the files. Cold start bootstraps the KB
from existing app state so it is useful before any trajectories exist.

At runtime the hybrid retriever routes the query to namespaces, blends BM25 and dense
candidates with reciprocal rank fusion, expands one hop over the memory graph, reranks
with task aware features, and packs a token budget bounded bundle into the agent's
system prompt. See [`docs/memory-model.md`](docs/memory-model.md).

### Replay and backtest (Tasks 5 + 6)

A deterministic sandbox is seeded from a snapshot with a frozen clock; reads come from
the snapshot and writes append to a log validators inspect. The backtest runs the agent
twice against the same seeded sandbox, with and without the KB mounted, and scores both
on a four axis rubric. See [`docs/eval-protocol.md`](docs/eval-protocol.md).

---

## The paired backtest

For each task the runner reconstructs the snapshot, seeds the sandbox, retrieves the
KB, runs both conditions against the same state, and scores each on four axes:

![backtest](docs/diagrams/backtest.svg)

The four rubric axes are scored separately so failures are interpretable: task outcome,
memory retrieval (precision and recall over expected memory), memory application, and
action validity. The headline delta uses the outcome grounded score so it is fair
across conditions. Statistics are paired: bootstrap confidence intervals, a Wilcoxon
signed rank test, and Cohen's kappa for inter rater agreement.

---

## Extending the platform

The platform is built so a teammate can add to it. The two most common extensions:

**Add a new SaaS app.** Implement one method on the `Integration` base, then register
one row. That is the whole change; the sync CLI, the worker, snapshots, and the
backtest pick it up automatically.

```python
# 1. Add the app to the App enum in src/ombench/events/schema.py
#    class App(StrEnum): ...; NOTION = "notion"

# 2. src/ombench/integrations/notion/sync.py
from ombench.integrations.base import Integration
from ombench.events import App, algebra

class NotionSync(Integration):
    app = App.NOTION
    entity_types = ("page",)

    def sync(self, *, ingested_at):
        for page in self._load():          # live client or fixture
            yield algebra.upsert_entity(
                app="notion", entity_type="page", entity_id=page["id"],
                payload=normalize(page), valid_at=..., ingested_at=ingested_at,
            )

# 3. Register one row in src/ombench/integrations/registry.py
REGISTRY["notion"] = IntegrationSpec("notion", NotionSync, "notion", "pages.json")
```

Gmail is wired exactly this way, which is the live proof the pattern works.

**Swap the storage backend.** The relational layer is behind a 7 method
`StorageBackend` interface. A `PostgresBackend` ships and is selected by setting
`OMBENCH_DATABASE_URL`; nothing above the storage layer changes.

```bash
pip install -e ".[postgres]"
export OMBENCH_DATABASE_URL=postgresql://ombench:ombench@localhost:5432/ombench
omb sync run all     # now runs against Postgres
```

Other seams: the `Embedder` interface (swap the hashing embedder for a real model), the
`LLMClient` interface (stub or Anthropic), and the `Judge` interface.

---

## Going to production

The platform is local first by default so it clones and runs with zero infra, but the
production seams are real, not aspirational:

- **Database**: a real `PostgresBackend` (`OMBENCH_DATABASE_URL`).
- **Sync worker**: `ombench.apps.worker.sync_worker` has a tested `run_once` cycle and a
  `run_forever` loop over the registry; a deployment adds a scheduler and live credentials.
- **Object storage**: `docker-compose.yml` provisions Postgres + pgvector + MinIO; the
  `BlobStore` is the seam for an S3 backed store.

The honest remaining gaps (no running scheduler, in process vector index, hashing
embedder, filesystem blobs) are catalogued in [`handoff.md`](handoff.md) with the reason
each is deferred and a high fidelity design for how to build it.

---

## Going live with real credentials

Copy `.env.example` to `.env` and set only what you want. Everything is additive; with
an empty environment the platform still runs end to end.

| Variable | Activates |
|---|---|
| `ANTHROPIC_API_KEY` | the real Claude agent under test and LLM judge (Opus 4.8, adaptive thinking) |
| `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` | real Slack workspace ingestion |
| `GOOGLE_CREDENTIALS_FILE`, `GOOGLE_TOKEN_FILE` | real Calendar / Docs / Drive ingestion |
| `OMBENCH_DATABASE_URL` | run against Postgres instead of SQLite |

When a credential is present the corresponding live path activates automatically; when
absent the platform uses synthetic fixtures and the deterministic agent and judge.

---

## Repository layout

```
src/ombench/
  storage/      content addressed blob store + StorageBackend (SQLite, Postgres)
  events/       canonical bitemporal AppEvent log with fold materialization
  traces/       agent agnostic trajectory capture, redaction, OTel interop, hook
  integrations/ Slack, Calendar, Docs, Gmail adapters + base + registry
  snapshots/    point in time materialization, Merkle root, diff
  memory/       KB compiler, scorer, resolver, hybrid retriever, bootstrap, extensions
  llm/          pluggable client (stub + Anthropic) and the agent under test
  replay/       deterministic sandbox, tool router, validators, fault injection
  eval/         tasks, four axis rubric, judges, paired runner, stats, reports, miner
  viz/          memory diff, provenance graph, approval queue, counterfactual, dashboard
  apps/         long running sync worker and programmatic replay runner
  cli/          the omb command groups
plugin/         the Claude Code capture plugin
benchmarks/     15 curated tasks + the curated memory seed
fixtures/       synthetic Slack, Calendar, Docs, Gmail, trajectory data
docs/           architecture, bitemporal, memory model, eval protocol, diagrams
notebooks/      benchmark mining and error analysis
```

---

## Testing

```bash
make test      # 407 tests, keyless
make cov       # with coverage (91% on the core substrate)
make lint      # ruff
make typecheck # mypy
```

Every push runs the keyless suite in CI (`.github/workflows/ci.yml`) on Python 3.11 and
3.12. The suite includes property based tests for content addressing and end to end
integration tests for sync, compile, replay, and the full backtest.

---

## Project documents

- [`docs/`](docs/) the design documentation set and PlantUML diagram sources, covering
  the architecture, the bitemporal model, the memory model, and the eval protocol.
- [`handoff.md`](handoff.md) the audited criteria checklist and the honest known gaps,
  each with a high fidelity design for how to build it.
- [`plan.md`](plan.md) the full execution plan.

## License

MIT. See [LICENSE](LICENSE).
