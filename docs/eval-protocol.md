# Evaluation protocol

The backtest measures whether the compiled knowledge base improves the agent under
identical historical conditions. The comparison is paired and the scoring is
decomposed.

## Paired protocol

For each `TaskSpec`:

1. Materialize the snapshot at the task's bitemporal coordinates.
2. Seed a deterministic sandbox from that snapshot.
3. Retrieve the compiled knowledge base for the task prompt.
4. Run the agent against the sandbox **without** memory mounted.
5. Run the agent again against the same seeded sandbox **with** memory mounted.
6. Score both runs on the same rubric and report the paired delta on the outcome
   grounded score.

The paired delta, win rate, and significance test are computed on the **outcome
grounded score** (task outcome and action validity), not the full four axis total.
The two memory axes are zero for the without memory condition by construction (it
retrieves nothing), so a delta on the total would be inflated regardless of agent
behavior. The four axis total stays as a per task diagnostic.

Task, snapshot, and sandbox are held deterministic across the two conditions, so the
only difference is whether the knowledge base is mounted. With the deterministic stub
the whole protocol is reproducible and keyless; with a live model, repeated runs per
condition can be averaged to handle stochasticity.

## Four axis rubric

A run is scored on four separate axes rather than one monolithic number, because that
decomposition makes ablations interpretable:

- **task outcome correctness**: did the agent achieve the expected end state
- **memory retrieval correctness**: did it retrieve the expected memory (precision and
  recall over expected memory, summarized as F1)
- **memory application correctness**: did the action actually reflect that memory
- **action validity and side effect safety**: were the writes valid and in scope

A run fails one of four distinct ways: it retrieved nothing, retrieved the wrong
memory, applied the right memory badly, or executed invalid actions. The rubric tells
them apart.

## Judges

The rule based judge is deterministic: it scores outcome and validity from the state
validators, retrieval from precision and recall, and application from whether the
achieved outcome reflects the expected memory. The Anthropic judge refines only the
application axis, with a prompt that is rubric grounded, evidence grounded, and **blind
to the with or without memory condition** to avoid the position, verbosity, and self
enhancement biases documented for LLM judges. It falls back to the rule based score on
any error.

## Statistics

- **Bootstrap confidence intervals** for the mean delta and the win rate, seeded for
  reproducibility.
- **Paired Wilcoxon signed rank** test on the score differences, with a normal
  approximation fallback when SciPy is absent.
- **Cohen's kappa** for inter rater agreement on a double scored subset, to verify a
  rule based pass and an LLM judged pass agree.

## What makes a good memory task

A good memory task is one where the answer depends on durable context that is not
reliably inferable from the current app state alone, and where the expected effect of
memory can be judged with explicit evidence. Each curated task documents, in its
`why_memory` field, exactly why the snapshot alone is insufficient. Tasks solvable from
the snapshot are deliberately excluded, because they would not test memory.
