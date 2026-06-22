"""Tests for the memory side extensions: budget, predictor, procedures, learned router."""

from __future__ import annotations

from datetime import datetime

from ombench.memory.budget import BudgetItem, optimize
from ombench.memory.learned_router import LearnedRouter, RoutingExample
from ombench.memory.predictor import (
    UsefulnessExample,
    UsefulnessPredictor,
    features_from,
)
from ombench.memory.procedure_synth import synthesize
from ombench.memory.schema import Namespace
from ombench.timeutil import UTC
from ombench.traces.schema import SpanKind, TraceRun, TraceSpan

# -- budget optimizer ----------------------------------------------------


def test_budget_picks_high_value_within_limit():
    items = [
        BudgetItem("a", value=1.0, tokens=10),
        BudgetItem("b", value=0.9, tokens=10),
        BudgetItem("c", value=0.1, tokens=10),
    ]
    plan = optimize(items, budget=20)
    assert set(plan.chosen) == {"a", "b"}
    assert plan.total_tokens <= 20


def test_budget_zero_returns_empty():
    plan = optimize([BudgetItem("a", 1.0, 10)], budget=0)
    assert plan.chosen == []


def test_budget_optimal_over_greedy_trap():
    # Greedy by density would take the two small ones; the big one is better here.
    items = [
        BudgetItem("big", value=10.0, tokens=10),
        BudgetItem("s1", value=3.0, tokens=6),
        BudgetItem("s2", value=3.0, tokens=6),
    ]
    plan = optimize(items, budget=10)
    assert plan.chosen == ["big"]


# -- usefulness predictor ------------------------------------------------


def test_predictor_learns_signal():
    pred = UsefulnessPredictor()
    examples = []
    for _ in range(50):
        examples.append(UsefulnessExample(features_from(mem_type="semantic", namespace="user",
                                                        confidence=0.9, rank=0), helped=True))
        examples.append(UsefulnessExample(features_from(mem_type="episodic", namespace="app_state",
                                                        confidence=0.2, rank=8), helped=False))
    pred.fit(examples)
    good = pred.predict(features_from(mem_type="semantic", namespace="user", confidence=0.9, rank=0))
    bad = pred.predict(features_from(mem_type="episodic", namespace="app_state", confidence=0.2, rank=8))
    assert good > bad


def test_predictor_deterministic():
    a = UsefulnessPredictor()
    b = UsefulnessPredictor()
    ex = [UsefulnessExample(features_from(mem_type="semantic", namespace="user", confidence=0.8, rank=1), helped=True)]
    a.fit(ex, epochs=5)
    b.fit(ex, epochs=5)
    f = features_from(mem_type="semantic", namespace="user", confidence=0.8, rank=1)
    assert a.predict(f) == b.predict(f)


# -- procedure synthesizer -----------------------------------------------


def _proc_run(i):
    r = TraceRun(agent="claude_code", started_at=datetime(2026, 5, 14, 17, 0, 0, tzinfo=UTC))
    r.add_span(TraceSpan(kind=SpanKind.TOOL, tool_name="gcal.get_event", tool_args={"event_id": "e"}))
    r.add_span(TraceSpan(kind=SpanKind.TOOL, tool_name="gcal.update_event", tool_args={"event_id": "e", "start": "x"}))
    return r


def test_synthesize_procedure():
    procs = synthesize([_proc_run(i) for i in range(3)], min_occurrences=2)
    assert len(procs) == 1
    proc = procs[0]
    assert proc.occurrences == 3
    assert [s.tool for s in proc.steps] == ["gcal.get_event", "gcal.update_event"]
    assert "start" in proc.steps[1].arg_keys
    assert "Procedure" in proc.to_markdown()


def test_no_procedure_below_threshold():
    assert synthesize([_proc_run(0)], min_occurrences=2) == []


# -- learned router ------------------------------------------------------


def test_learned_router_separates_namespaces():
    router = LearnedRouter()
    examples = [
        RoutingExample("what time do I prefer for my meetings", Namespace.USER),
        RoutingExample("my personal preference for lunch", Namespace.USER),
        RoutingExample("our team announcement convention", Namespace.TEAM),
        RoutingExample("the team norm for launches", Namespace.TEAM),
    ]
    router.fit(examples)
    user_scores = router.route("what is my preference", blend_rule_based=False)
    assert user_scores.top(1)[0] == Namespace.USER


def test_learned_router_blends_with_rules():
    router = LearnedRouter()
    router.fit([RoutingExample("our team convention", Namespace.TEAM)])
    scores = router.route("our team announcement convention")
    # Blended scores still sum to a sensible distribution.
    assert Namespace.TEAM in scores.top(2)
