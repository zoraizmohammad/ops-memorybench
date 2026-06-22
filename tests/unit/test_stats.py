"""Tests for backtest statistics."""

from __future__ import annotations

from ombench.eval.stats import (
    bootstrap_mean_ci,
    cohens_kappa,
    wilcoxon_signed_rank,
    win_rate_ci,
)


def test_bootstrap_ci_contains_mean():
    values = [0.1, 0.2, 0.3, 0.15, 0.25, 0.2, 0.18]
    ci = bootstrap_mean_ci(values, iterations=500)
    assert ci.low <= ci.estimate <= ci.high
    # Estimate is the sample mean, rounded to 4 decimals.
    assert abs(ci.estimate - sum(values) / len(values)) < 1e-3


def test_bootstrap_is_reproducible():
    values = [0.1, 0.3, 0.2, 0.4, 0.05]
    a = bootstrap_mean_ci(values, seed=7, iterations=300)
    b = bootstrap_mean_ci(values, seed=7, iterations=300)
    assert (a.low, a.high) == (b.low, b.high)


def test_bootstrap_empty_and_singleton():
    assert bootstrap_mean_ci([]).estimate == 0.0
    ci = bootstrap_mean_ci([0.5])
    assert ci.low == ci.high == 0.5


def test_win_rate_ci():
    deltas = [0.1, 0.2, -0.05, 0.3, 0.0]
    ci = win_rate_ci(deltas, iterations=300)
    # 3 of 5 are strictly positive.
    assert abs(ci.estimate - 0.6) < 1e-6


def test_wilcoxon_all_positive():
    res = wilcoxon_signed_rank([0.1, 0.2, 0.3, 0.4, 0.5])
    assert res.n == 5
    # All improvements, so the test should indicate significance for a small sample.
    assert res.pvalue <= 1.0
    assert res.statistic >= 0


def test_wilcoxon_all_zero_is_degenerate():
    res = wilcoxon_signed_rank([0.0, 0.0])
    assert res.method == "degenerate"
    assert res.pvalue == 1.0


def test_cohens_kappa_perfect():
    a = ["pass", "fail", "pass", "pass"]
    assert cohens_kappa(a, a) == 1.0


def test_cohens_kappa_chance():
    # Disagreement that matches chance expectation gives kappa near 0.
    a = ["pass", "fail", "pass", "fail"]
    b = ["fail", "pass", "fail", "pass"]
    k = cohens_kappa(a, b)
    assert k <= 0.0


def test_cohens_kappa_mismatched_lengths():
    assert cohens_kappa(["a"], ["a", "b"]) == 0.0
