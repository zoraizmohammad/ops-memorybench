"""Tests for backtest report generation."""

from __future__ import annotations

from ombench.eval.reports import summarize, to_markdown
from ombench.eval.rubrics import RubricScores
from ombench.eval.runner import BacktestReport, ConditionResult, TaskResult


def _cond(condition, total_outcome, validity=1.0):
    scores = RubricScores(
        task_outcome=total_outcome, memory_retrieval=1.0,
        memory_application=total_outcome, action_validity=validity,
    )
    return ConditionResult(
        condition=condition, scores=scores, retrieved_claims=[], writes=[],
        final_text="", input_tokens=10, output_tokens=5, cost_usd=0.0,
    )


def _report():
    results = [
        TaskResult("t1", without_memory=_cond("without_memory", 0.0),
                   with_memory=_cond("with_memory", 1.0)),
        TaskResult("t2", without_memory=_cond("without_memory", 1.0),
                   with_memory=_cond("with_memory", 1.0)),
    ]
    return BacktestReport(results=results)


def test_summarize_metrics():
    s = summarize(_report())
    assert s["n_tasks"] == 2
    assert s["mean_total_with"] >= s["mean_total_without"]
    assert s["mean_delta"] >= 0
    assert 0.0 <= s["win_rate"] <= 1.0


def test_markdown_contains_table():
    md = to_markdown(_report())
    assert "Backtest results" in md
    assert "without memory" in md
    assert "with memory" in md
    assert "t1" in md
    assert "total delta" in md


def test_empty_report():
    s = summarize(BacktestReport(results=[]))
    assert s["n_tasks"] == 0
    assert s["win_rate"] == 0.0
