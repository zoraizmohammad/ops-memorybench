"""Prompt time memory budget optimizer.

Long context is not free: relevant information lost in a large context is used poorly,
so a tight, high value memory bundle beats dumping the whole knowledge base. This
turns context packing into an explicit optimization: given scored candidate memories
and a token budget, choose the subset that maximizes total value per token.

This is the classic 0/1 knapsack. For the small candidate sets a single query
produces, an exact dynamic program is cheap and gives the optimal pack; a greedy
value density fallback covers pathological sizes. The optimizer is deterministic so a
backtest is reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BudgetItem:
    """A candidate memory with a value and a token cost."""

    id: str
    value: float
    tokens: int


@dataclass
class BudgetPlan:
    chosen: list[str]
    total_value: float
    total_tokens: int


def optimize(items: list[BudgetItem], budget: int) -> BudgetPlan:
    """Choose the subset of items maximizing value within the token budget.

    Uses an exact dynamic program when the budget is modest, falling back to a greedy
    value density heuristic for very large budgets to keep it fast.
    """
    items = [i for i in items if i.tokens >= 0]
    if budget <= 0 or not items:
        return BudgetPlan(chosen=[], total_value=0.0, total_tokens=0)

    if budget <= 5000 and len(items) <= 200:
        return _knapsack(items, budget)
    return _greedy(items, budget)


def _knapsack(items: list[BudgetItem], budget: int) -> BudgetPlan:
    # dp[w] = best value achievable with capacity w; track chosen via parent sets.
    best: list[float] = [0.0] * (budget + 1)
    pick: list[list[str]] = [[] for _ in range(budget + 1)]
    for item in items:
        cost = max(1, item.tokens)
        for w in range(budget, cost - 1, -1):
            cand = best[w - cost] + item.value
            if cand > best[w]:
                best[w] = cand
                pick[w] = pick[w - cost] + [item.id]
    chosen = pick[budget]
    by_id = {i.id: i for i in items}
    total_tokens = sum(max(1, by_id[i].tokens) for i in chosen)
    return BudgetPlan(chosen=chosen, total_value=round(best[budget], 4), total_tokens=total_tokens)


def _greedy(items: list[BudgetItem], budget: int) -> BudgetPlan:
    ranked = sorted(items, key=lambda i: (-(i.value / max(1, i.tokens)), i.id))
    chosen: list[str] = []
    value = 0.0
    used = 0
    for item in ranked:
        cost = max(1, item.tokens)
        if used + cost <= budget:
            chosen.append(item.id)
            value += item.value
            used += cost
    return BudgetPlan(chosen=chosen, total_value=round(value, 4), total_tokens=used)
