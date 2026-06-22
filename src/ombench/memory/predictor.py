"""Memory usefulness predictor.

Learns which memories are worth mounting from backtest outcomes. After running the
benchmark we know, for each memory that was retrieved, whether the run it informed
succeeded. This fits a simple online logistic model over memory features (type,
namespace, confidence, retrieval rank, prior success rate) to predict the probability
that mounting a given memory for a query will help.

The model is a lightweight stochastic gradient logistic regression with no external
dependency, so it trains and predicts deterministically given a fixed example order.
It is a learned refinement of the hand authored utility function, not a replacement;
its output can feed the budget optimizer's value term.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class UsefulnessExample:
    """One training example: features of a mounted memory and whether it helped."""

    features: dict[str, float]
    helped: bool


@dataclass
class UsefulnessPredictor:
    """An online logistic regression over memory features."""

    weights: dict[str, float] = field(default_factory=dict)
    bias: float = 0.0
    lr: float = 0.1

    def predict(self, features: dict[str, float]) -> float:
        z = self.bias + sum(self.weights.get(k, 0.0) * v for k, v in features.items())
        return _sigmoid(z)

    def update(self, example: UsefulnessExample) -> None:
        """One gradient step on a single example."""
        pred = self.predict(example.features)
        target = 1.0 if example.helped else 0.0
        error = pred - target
        self.bias -= self.lr * error
        for k, v in example.features.items():
            self.weights[k] = self.weights.get(k, 0.0) - self.lr * error * v

    def fit(self, examples: list[UsefulnessExample], *, epochs: int = 20) -> None:
        """Train over examples for several epochs in a fixed order for reproducibility."""
        for _ in range(epochs):
            for ex in examples:
                self.update(ex)


def _sigmoid(x: float) -> float:
    if x < -60:
        return 0.0
    if x > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def features_from(*, mem_type: str, namespace: str, confidence: float, rank: int) -> dict[str, float]:
    """Build a feature vector for a memory in a retrieval context.

    Categorical type and namespace are one hot; confidence and inverse rank are
    numeric. Inverse rank rewards memories that ranked highly in retrieval.
    """
    feats = {
        f"type={mem_type}": 1.0,
        f"ns={namespace}": 1.0,
        "confidence": confidence,
        "inv_rank": 1.0 / (rank + 1),
    }
    return feats
