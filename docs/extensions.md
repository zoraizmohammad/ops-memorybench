# Extensions

Beyond the six core tasks, ombench implements the feasible and stretch extensions, and
the research extensions that strengthen the platform.

## Feasible

| Extension | Where | What it does |
|---|---|---|
| SaaS Git CLI | `omb saasgit` | `log`, `show`, `diff`, `checkout`, `ls` over reconstructed SaaS history, the way git works over code |
| Memory diff viewer | `ombench.viz.memory_diff` | Diffs two compiled knowledge base states into added, deactivated, reactivated |
| Provenance graph | `ombench.viz.provenance`, `omb viz provenance` | Renders every memory's evidence chain and supersede edges as text and Graphviz DOT |
| Human approval queue | `ombench.viz.approval_queue` | Routes mid confidence and personal candidates for human review before they enter the KB |
| Task miner | `ombench.eval.miner` | Surfaces candidate benchmark tasks from repeated corrections, recurring workflows, and durable statements |
| Budget optimizer | `ombench.memory.budget` | Solves the value per token knapsack to pack the most useful memory into the context budget |

## Stretch

| Extension | Where | What it does |
|---|---|---|
| Counterfactual explorer | `ombench.viz.counterfactual` | Ranks alternate retrieved memory packs head to head against the same seeded snapshot |
| Usefulness predictor | `ombench.memory.predictor` | Learns from backtest outcomes which memories help, via online logistic regression |
| Procedure synthesizer | `ombench.memory.procedure_synth` | Converts repeated tool sequences into structured executable playbooks |
| Time travel debugging UI | `ombench.viz.timetravel`, `omb viz timetravel` | Walks an entity through its versions with the diff at each step, plus a workspace activity feed |

## Research

| Extension | Where | What it does |
|---|---|---|
| Learned namespace router | `ombench.memory.learned_router` | Fits per namespace bag of words models from labeled queries and blends with the rule based prior |
| Fault injected replay contracts | `ombench.replay.faults` | Injects deterministic tool errors, rate limits, and stale reads to probe agent resilience under adverse conditions |

## Demo surface

`omb viz dashboard` runs the full backtest and writes a self contained HTML report with
the headline with versus without memory comparison and the per task per axis breakdown.
