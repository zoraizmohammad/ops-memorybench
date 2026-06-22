"""Learned namespace router.

The rule based router scores namespaces from cue words. This learned variant fits a
per namespace logistic model over query token features from labeled examples, so the
routing policy can adapt to a team's vocabulary rather than relying on fixed cues. It
plugs in behind the same interface as the rule based router, returning the same
:class:`RouteScores` shape.

The model is a small bag of words logistic regression per namespace, trained
deterministically, with no external dependency. With no training it falls back to a
uniform prior, and it composes with the rule based router by averaging.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .bm25 import tokenize
from .router import RouteScores
from .router import route as rule_route
from .schema import Namespace


@dataclass
class RoutingExample:
    query: str
    namespace: Namespace


@dataclass
class LearnedRouter:
    """Per namespace bag of words logistic models for query routing."""

    weights: dict[Namespace, dict[str, float]] = field(default_factory=dict)
    bias: dict[Namespace, float] = field(default_factory=dict)
    lr: float = 0.2

    def _score_ns(self, ns: Namespace, tokens: list[str]) -> float:
        w = self.weights.get(ns, {})
        z = self.bias.get(ns, 0.0) + sum(w.get(t, 0.0) for t in tokens)
        return _sigmoid(z)

    def fit(self, examples: list[RoutingExample], *, epochs: int = 30) -> None:
        """Train one one vs rest logistic model per namespace."""
        all_ns = list(Namespace)
        for ns in all_ns:
            self.weights.setdefault(ns, {})
            self.bias.setdefault(ns, 0.0)
        for _ in range(epochs):
            for ex in examples:
                tokens = tokenize(ex.query)
                for ns in all_ns:
                    target = 1.0 if ex.namespace == ns else 0.0
                    pred = self._score_ns(ns, tokens)
                    error = pred - target
                    self.bias[ns] -= self.lr * error
                    for t in tokens:
                        self.weights[ns][t] = self.weights[ns].get(t, 0.0) - self.lr * error

    def route(self, query: str, *, blend_rule_based: bool = True) -> RouteScores:
        """Score namespaces for a query, optionally blending the rule based prior."""
        tokens = tokenize(query)
        raw = {ns: self._score_ns(ns, tokens) for ns in Namespace}
        total = sum(raw.values()) or 1.0
        learned = {ns: v / total for ns, v in raw.items()}
        if not blend_rule_based:
            return RouteScores(scores=learned)
        rule = rule_route(query).scores
        blended = {ns: round((learned[ns] + rule.get(ns, 0.0)) / 2, 4) for ns in Namespace}
        return RouteScores(scores=blended)


def _sigmoid(x: float) -> float:
    if x < -60:
        return 0.0
    if x > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))
