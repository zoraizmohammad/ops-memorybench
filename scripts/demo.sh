#!/usr/bin/env bash
# End to end walkthrough of the ombench platform. Runs entirely keyless against the
# bundled synthetic fixtures and the deterministic agent and judge. Each step is a
# real CLI command, so this doubles as living documentation of the platform.
set -euo pipefail

OMB="${OMB:-.venv/bin/omb}"
export OMBENCH_HOME="${OMBENCH_HOME:-.ombench-demo}"

echo "== 1. configuration (all live paths off, running keyless) =="
$OMB info

echo
echo "== 2. sync SaaS state into the bitemporal event log =="
$OMB sync run all
$OMB sync stats

echo
echo "== 3. git for SaaS: reconstruct a 1:1 before and after it was rescheduled =="
echo "-- before the reschedule --"
$OMB saasgit show gcal event ev_1on1_bob --at 2026-05-10T00:00:00Z
echo "-- latest --"
$OMB saasgit show gcal event ev_1on1_bob

echo
echo "== 4. compile the knowledge base from app state (cold start) =="
$OMB memory bootstrap
$OMB memory list

echo
echo "== 5. retrieve memory for a task prompt =="
$OMB memory retrieve "reschedule my 1:1 what time do I prefer"

echo
echo "== 6. backtest with cold start memory only (bootstrapped from app state) =="
echo "   Cold start memory already lifts some tasks, but covers fewer than a team's"
echo "   accumulated knowledge would."
$OMB eval run

echo
echo "== 7. full backtest with the curated knowledge base mounted =="
echo "   omb demo syncs, loads the curated knowledge base a team would have compiled"
echo "   from its history, and runs the paired backtest over all fifteen tasks."
$OMB demo

echo
echo "== 8. write the HTML dashboard =="
$OMB viz dashboard --out "$OMBENCH_HOME/backtest.html"

echo
echo "Done. Open $OMBENCH_HOME/backtest.html for the results dashboard."
