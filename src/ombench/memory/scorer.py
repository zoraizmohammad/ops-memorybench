"""Scoring candidates into confidence and promotion decisions.

Two models live here, both operationalizing the formulas from the design:

- **Confidence** is evidence based. A claim is more trustworthy when a user stated it
  explicitly, when behavior repeats, when multiple sources corroborate, and when the
  source is reliable; it is less trustworthy with contradictions, extractor
  uncertainty, and age. This is a logistic combination of those features.

- **Utility** estimates whether a memory is worth mounting for a given query and
  time. It rewards usefulness and impact and penalizes privacy risk, contradiction
  risk, staleness, and read cost.

Both are deterministic given their inputs so the keyless path is reproducible. The
weights are hand chosen but structured, which is more rigorous than a flat weighted
sum while staying simple enough to reason about.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .candidate_extractor import ExtractedCandidate


def sigmoid(x: float) -> float:
    # Clamp to avoid overflow on extreme inputs.
    if x < -60:
        return 0.0
    if x > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class ConfidenceFeatures:
    """Evidence features feeding the confidence model."""

    explicit_user_statement: bool = False
    repeated_behavior: int = 0  # count of corroborating occurrences beyond the first
    corroborating_sources: int = 0  # distinct sources stating the same claim
    source_reliability: float = 0.5  # 0..1
    contradiction_count: int = 0
    extractor_uncertainty: float = 0.3  # 0..1
    age_days: float = 0.0


# Weights for the evidence based confidence logistic. Chosen to make an explicit user
# statement with a reliable source land around 0.8 and a lone uncertain extraction
# land below 0.5.
_B = {
    "intercept": -0.6,
    "explicit": 1.8,
    "repeated": 0.5,
    "corroborating": 0.6,
    "reliability": 1.2,
    "contradiction": -1.1,
    "uncertainty": -1.0,
    "age": -0.02,
}


def confidence(features: ConfidenceFeatures) -> float:
    """Evidence based confidence in a claim, in the range 0..1."""
    z = (
        _B["intercept"]
        + _B["explicit"] * (1.0 if features.explicit_user_statement else 0.0)
        + _B["repeated"] * features.repeated_behavior
        + _B["corroborating"] * features.corroborating_sources
        + _B["reliability"] * features.source_reliability
        + _B["contradiction"] * features.contradiction_count
        + _B["uncertainty"] * features.extractor_uncertainty
        + _B["age"] * features.age_days
    )
    return round(sigmoid(z), 4)


# Source reliability priors by where a candidate came from.
_SOURCE_RELIABILITY = {
    "explicit": 0.85,
    "correction": 0.8,
    "procedure": 0.7,
    "app_norm": 0.6,
}


def features_for(
    candidate: ExtractedCandidate,
    *,
    corroborating_sources: int = 0,
    contradiction_count: int = 0,
    age_days: float = 0.0,
) -> ConfidenceFeatures:
    """Build confidence features for an extracted candidate.

    The extractor's own ``confidence_hint`` is interpreted as inverse uncertainty:
    a higher hint means lower extractor uncertainty.
    """
    hint = candidate.candidate.confidence_hint
    uncertainty = 1.0 - hint if hint is not None else 0.4
    repeated = int(candidate.extra.get("occurrences", 1)) - 1
    return ConfidenceFeatures(
        explicit_user_statement=candidate.source_kind in ("explicit", "correction"),
        repeated_behavior=max(0, repeated),
        corroborating_sources=corroborating_sources,
        source_reliability=_SOURCE_RELIABILITY.get(candidate.source_kind, 0.5),
        contradiction_count=contradiction_count,
        extractor_uncertainty=max(0.0, min(1.0, uncertainty)),
        age_days=age_days,
    )


def score_candidate(
    candidate: ExtractedCandidate,
    *,
    corroborating_sources: int = 0,
    contradiction_count: int = 0,
    age_days: float = 0.0,
) -> float:
    """Compute the confidence to attach to a candidate when compiling it."""
    feats = features_for(
        candidate,
        corroborating_sources=corroborating_sources,
        contradiction_count=contradiction_count,
        age_days=age_days,
    )
    return confidence(feats)


@dataclass
class UtilityFeatures:
    """Features feeding the retrieval time utility model."""

    p_useful: float = 0.5  # probability the memory helps this query
    impact: float = 0.5  # how much it helps if used
    privacy_risk: float = 0.0
    contradiction_risk: float = 0.0
    staleness: float = 0.0
    read_cost: float = 0.0  # normalized token cost of including it


_LAMBDA = {"privacy": 0.5, "contradiction": 0.6, "staleness": 0.3, "read": 0.2}


def utility(features: UtilityFeatures) -> float:
    """Expected value of mounting a memory for a query, can be negative.

    A negative utility means the memory costs more than it helps and should not be
    packed into the context budget.
    """
    return round(
        features.p_useful * features.impact
        - _LAMBDA["privacy"] * features.privacy_risk
        - _LAMBDA["contradiction"] * features.contradiction_risk
        - _LAMBDA["staleness"] * features.staleness
        - _LAMBDA["read"] * features.read_cost,
        4,
    )
