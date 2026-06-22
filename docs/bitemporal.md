# Bitemporal state model

The central state equation of the platform is:

```
S(T, tau) = fold(S0, { e | valid_at(e) <= T and ingested_at(e) <= tau })
```

Every event carries two times:

- **`valid_at`** is when the change took effect in the source application.
- **`ingested_at`** is when ombench learned about it.

State at a bitemporal point is computed by folding the subset of events whose
validity time is at or before `T` and whose ingestion time is at or before `tau`.

## Why two times, not one

A single event time is not enough for honest backtesting. SaaS sync is not perfectly
synchronous: Calendar sync tokens expire and force a resync, Drive changes are
retrieved asynchronously, and events can arrive after the fact. If a backtest folds by
event time alone, it can hand the agent information it would not actually have had at
the time the historical task ran.

The ingest time filter prevents that leakage. To replay a task that happened at `T`,
the harness materializes `S(T, tau)` with `tau` set to the moment the system could
realistically have known the state. An event that took effect before `T` but was only
ingested after `tau` is correctly excluded.

`tests/unit/test_event_store.py::test_ingest_time_travel_prevents_leakage` exercises
exactly this: a late arriving backfill is invisible at an earlier ingest time and
visible at a later one.

## The fold

The fold is deterministic. Events are ordered by `valid_at` then by a monotonic
ingest sequence as a tie breaker, so two materializations of the same bitemporal point
produce byte identical state. Upserts merge payloads; deletes tombstone the entity but
are retained; edges fold into live target sets for membership and attendance; appended
versions (used for Docs content) keep every version while the latest wins.

## Append only

Nothing is ever updated or deleted in the event log. Deletions are themselves events.
This is what makes "git for SaaS" possible: any past state is reconstructable because
the full history is retained, and a snapshot is just a fold to a chosen point.
