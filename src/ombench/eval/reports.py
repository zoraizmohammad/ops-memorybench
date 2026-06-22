"""Backtest report generation.

Turns a :class:`BacktestReport` into the artifacts a reviewer wants to see: a paired
with vs without memory results table, the per axis breakdown, and the supporting
statistics. Markdown is the primary format because it drops straight into the README
and the writeup; a compact summary dict supports programmatic use and the HTML
dashboard.
"""

from __future__ import annotations

from typing import Any

from .runner import BacktestReport
from .stats import bootstrap_mean_ci, cohens_kappa, wilcoxon_signed_rank, win_rate_ci


def summarize(report: BacktestReport) -> dict[str, Any]:
    """Compute the headline metrics and statistics for a backtest report.

    The headline delta, win rate, and significance test are computed on the outcome
    grounded score (task outcome and action validity), which is fair to compare
    across the with and without memory conditions. The full four axis totals are
    also reported as a diagnostic, but they are not the basis of the comparison
    because the two memory axes are zero for the without condition by construction.
    """
    deltas = report.deltas()  # outcome grounded
    with_outcome = [r.with_memory.scores.outcome_score for r in report.results]
    without_outcome = [r.without_memory.scores.outcome_score for r in report.results]
    with_totals = [r.with_memory.scores.total for r in report.results]
    without_totals = [r.without_memory.scores.total for r in report.results]

    delta_ci = bootstrap_mean_ci(deltas)
    wr_ci = win_rate_ci(deltas)
    wilcoxon = wilcoxon_signed_rank(deltas)

    def mean(xs: list[float]) -> float:
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    return {
        "n_tasks": len(report.results),
        "mean_outcome_with": mean(with_outcome),
        "mean_outcome_without": mean(without_outcome),
        "mean_total_with": mean(with_totals),
        "mean_total_without": mean(without_totals),
        "mean_delta": delta_ci.estimate,
        "delta_ci": [delta_ci.low, delta_ci.high],
        "win_rate": report.win_rate(),
        "win_rate_ci": [wr_ci.low, wr_ci.high],
        "wilcoxon_p": wilcoxon.pvalue,
        "wilcoxon_method": wilcoxon.method,
        "success_with": mean([1.0 if r.with_memory.scores.success else 0.0 for r in report.results]),
        "success_without": mean([1.0 if r.without_memory.scores.success else 0.0 for r in report.results]),
    }


def to_markdown(report: BacktestReport) -> str:
    """Render the backtest report as markdown."""
    s = summarize(report)
    lines: list[str] = []
    lines.append("# Backtest results")
    lines.append("")
    lines.append(f"Tasks evaluated: {s['n_tasks']}")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append("| metric | without memory | with memory | delta |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| mean outcome score | {s['mean_outcome_without']} | {s['mean_outcome_with']} | "
        f"{s['mean_delta']} |"
    )
    lines.append(
        f"| success rate | {s['success_without']} | {s['success_with']} | "
        f"{round(s['success_with'] - s['success_without'], 4)} |"
    )
    lines.append("")
    lines.append(
        "The outcome score (task outcome and action validity) is the basis of the "
        "comparison. The four axis rubric total is diagnostic only, because its two "
        "memory axes are zero for the without memory condition by construction."
    )
    lines.append(
        f"Mean outcome delta 95% CI [{s['delta_ci'][0]}, {s['delta_ci'][1]}]; "
        f"win rate {s['win_rate']} (CI [{s['win_rate_ci'][0]}, {s['win_rate_ci'][1]}]); "
        f"Wilcoxon p {s['wilcoxon_p']} ({s['wilcoxon_method']})."
    )
    lines.append("")
    lines.append("## Per task")
    lines.append("")
    lines.append("| task | outcome w/o | outcome w/ | retrieval w/ | application w/ | validity w/ | outcome delta |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in report.results:
        wo = r.without_memory.scores
        wm = r.with_memory.scores
        lines.append(
            f"| {r.task_id} | {wo.task_outcome} | {wm.task_outcome} | "
            f"{wm.memory_retrieval} | {wm.memory_application} | {wm.action_validity} | "
            f"{r.outcome_delta} |"
        )
    lines.append("")
    return "\n".join(lines)


def double_score_kappa(report: BacktestReport, second_pass: BacktestReport) -> float:
    """Cohen's kappa on the success labels of two scoring passes over the same tasks.

    Used to verify reviewer agreement on a double scored subset, for example a rule
    based pass and an LLM judged pass.
    """
    a = [1 if r.with_memory.scores.success else 0 for r in report.results]
    b = [1 if r.with_memory.scores.success else 0 for r in second_pass.results]
    return cohens_kappa(a, b)
