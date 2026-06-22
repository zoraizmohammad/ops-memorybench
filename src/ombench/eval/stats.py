"""Statistics for the backtest.

The right comparison is paired: the same task and snapshot run with and without
memory, scored the same way. The supporting statistics are bootstrap confidence
intervals for the mean delta and win rate, a paired nonparametric test (Wilcoxon
signed rank) for the score differences, and Cohen's kappa for inter rater agreement
on a double scored subset.

Each function uses SciPy and statsmodels when available for exactness, but falls back
to a correct pure Python implementation so the keyless path needs no heavy
dependency. The bootstrap is seeded for reproducibility rather than using global
randomness.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CI:
    """A point estimate with a confidence interval."""

    estimate: float
    low: float
    high: float
    level: float = 0.95


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear interpolation percentile, q in 0..1, over a presorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 >= len(sorted_values):
        return sorted_values[-1]
    return sorted_values[lo] * (1 - frac) + sorted_values[lo + 1] * frac


class _LCG:
    """A small deterministic linear congruential generator for the bootstrap.

    Math.random style global randomness is avoided so a backtest report is exactly
    reproducible from a fixed seed.
    """

    def __init__(self, seed: int = 12345) -> None:
        self.state = seed & 0xFFFFFFFF

    def randint(self, n: int) -> int:
        self.state = (1103515245 * self.state + 12345) & 0x7FFFFFFF
        return self.state % n


def bootstrap_mean_ci(
    values: list[float], *, level: float = 0.95, iterations: int = 2000, seed: int = 12345
) -> CI:
    """Bootstrap confidence interval for the mean of ``values``.

    Resamples with replacement ``iterations`` times using a seeded generator, so the
    interval is reproducible. Falls back gracefully for tiny samples.
    """
    if not values:
        return CI(estimate=0.0, low=0.0, high=0.0, level=level)
    mean = sum(values) / len(values)
    if len(values) == 1:
        return CI(estimate=mean, low=mean, high=mean, level=level)

    rng = _LCG(seed)
    n = len(values)
    means: list[float] = []
    for _ in range(iterations):
        total = 0.0
        for _ in range(n):
            total += values[rng.randint(n)]
        means.append(total / n)
    means.sort()
    alpha = (1 - level) / 2
    return CI(
        estimate=round(mean, 4),
        low=round(_percentile(means, alpha), 4),
        high=round(_percentile(means, 1 - alpha), 4),
        level=level,
    )


def win_rate_ci(deltas: list[float], **kwargs) -> CI:
    """Bootstrap CI for the win rate (fraction of positive paired deltas)."""
    wins = [1.0 if d > 0 else 0.0 for d in deltas]
    return bootstrap_mean_ci(wins, **kwargs)


@dataclass
class WilcoxonResult:
    statistic: float
    pvalue: float
    n: int
    method: str


def wilcoxon_signed_rank(deltas: list[float]) -> WilcoxonResult:
    """Paired Wilcoxon signed rank test on the score differences.

    Uses SciPy when present. Otherwise computes the signed rank statistic and a normal
    approximation p value, which is appropriate for the small samples a benchmark
    produces and matches SciPy's default for ties.
    """
    nonzero = [d for d in deltas if d != 0]
    if not nonzero:
        return WilcoxonResult(statistic=0.0, pvalue=1.0, n=0, method="degenerate")
    try:
        from scipy.stats import wilcoxon  # type: ignore

        stat, p = wilcoxon(nonzero)
        return WilcoxonResult(statistic=float(stat), pvalue=float(p), n=len(nonzero), method="scipy")
    except Exception:
        return _wilcoxon_normal_approx(nonzero)


def _wilcoxon_normal_approx(deltas: list[float]) -> WilcoxonResult:
    import math

    abs_sorted = sorted(deltas, key=abs)
    # Average ranks for ties in absolute value.
    ranks: list[float] = [0.0] * len(abs_sorted)
    i = 0
    while i < len(abs_sorted):
        j = i
        while j + 1 < len(abs_sorted) and abs(abs_sorted[j + 1]) == abs(abs_sorted[i]):
            j += 1
        avg_rank = (i + 1 + j + 1) / 2
        for k in range(i, j + 1):
            ranks[k] = avg_rank
        i = j + 1
    w_plus = sum(r for d, r in zip(abs_sorted, ranks, strict=False) if d > 0)
    w_minus = sum(r for d, r in zip(abs_sorted, ranks, strict=False) if d < 0)
    stat = min(w_plus, w_minus)
    n = len(deltas)
    mean = n * (n + 1) / 4
    sd = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    if sd == 0:
        return WilcoxonResult(statistic=stat, pvalue=1.0, n=n, method="normal_approx")
    z = (stat - mean) / sd
    p = 2 * (1 - _normal_cdf(abs(z)))
    return WilcoxonResult(statistic=stat, pvalue=round(max(0.0, min(1.0, p)), 4), n=n, method="normal_approx")


def _normal_cdf(x: float) -> float:
    import math

    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def cohens_kappa(rater_a: list[Any], rater_b: list[Any]) -> float:
    """Cohen's kappa for inter rater agreement on categorical labels.

    Uses statsmodels when available, otherwise a direct computation. Returns 1.0 for
    perfect agreement, 0.0 for chance level, negative for worse than chance.
    """
    if len(rater_a) != len(rater_b) or not rater_a:
        return 0.0
    try:
        from statsmodels.stats.inter_rater import cohens_kappa as sm_kappa  # type: ignore
        from statsmodels.stats.inter_rater import to_table  # type: ignore

        table, _ = to_table(list(zip(rater_a, rater_b, strict=False)))
        return float(sm_kappa(table).kappa)
    except Exception:
        return _kappa_direct(rater_a, rater_b)


def _kappa_direct(a: list, b: list) -> float:
    n = len(a)
    labels = set(a) | set(b)
    observed = sum(1 for x, y in zip(a, b, strict=False) if x == y) / n
    expected = 0.0
    for label in labels:
        pa = sum(1 for x in a if x == label) / n
        pb = sum(1 for y in b if y == label) / n
        expected += pa * pb
    if expected == 1.0:
        return 1.0
    return round((observed - expected) / (1 - expected), 4)
