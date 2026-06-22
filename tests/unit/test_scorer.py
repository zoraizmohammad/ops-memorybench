"""Tests for the confidence and utility scoring models."""

from __future__ import annotations

from ombench.memory.candidate_extractor import ExtractedCandidate
from ombench.memory.scorer import (
    ConfidenceFeatures,
    UtilityFeatures,
    confidence,
    score_candidate,
    sigmoid,
    utility,
)
from ombench.traces.schema import MemoryCandidate


def test_sigmoid_bounds():
    assert sigmoid(-1000) == 0.0
    assert sigmoid(1000) == 1.0
    assert 0.49 < sigmoid(0) < 0.51


def test_explicit_statement_raises_confidence():
    low = confidence(ConfidenceFeatures(explicit_user_statement=False, source_reliability=0.3))
    high = confidence(ConfidenceFeatures(explicit_user_statement=True, source_reliability=0.85))
    assert high > low
    assert high > 0.7


def test_contradictions_lower_confidence():
    clean = confidence(ConfidenceFeatures(explicit_user_statement=True, source_reliability=0.8))
    contradicted = confidence(ConfidenceFeatures(
        explicit_user_statement=True, source_reliability=0.8, contradiction_count=3,
    ))
    assert contradicted < clean


def test_corroboration_and_repetition_help():
    base = confidence(ConfidenceFeatures(source_reliability=0.5))
    more = confidence(ConfidenceFeatures(
        source_reliability=0.5, repeated_behavior=3, corroborating_sources=2,
    ))
    assert more > base


def test_age_decays_confidence():
    fresh = confidence(ConfidenceFeatures(explicit_user_statement=True, age_days=0))
    old = confidence(ConfidenceFeatures(explicit_user_statement=True, age_days=365))
    assert old < fresh


def _cand(kind="explicit", hint=0.7, occurrences=1):
    return ExtractedCandidate(
        candidate=MemoryCandidate(text="x", confidence_hint=hint),
        source_kind=kind, evidence_ref="trace_1",
        extra={"occurrences": occurrences} if occurrences > 1 else {},
    )


def test_score_candidate_explicit_high():
    score = score_candidate(_cand("explicit", hint=0.8))
    assert score > 0.6


def test_score_candidate_app_norm_lower_than_explicit():
    explicit = score_candidate(_cand("explicit", hint=0.7))
    app_norm = score_candidate(_cand("app_norm", hint=0.5))
    assert app_norm < explicit


def test_repeated_procedure_scores_higher():
    once = score_candidate(_cand("procedure", hint=0.6, occurrences=1))
    many = score_candidate(_cand("procedure", hint=0.6, occurrences=5))
    assert many > once


def test_utility_positive_for_useful_memory():
    u = utility(UtilityFeatures(p_useful=0.9, impact=0.8))
    assert u > 0.5


def test_utility_penalizes_risk_and_staleness():
    good = utility(UtilityFeatures(p_useful=0.8, impact=0.8))
    risky = utility(UtilityFeatures(
        p_useful=0.8, impact=0.8, privacy_risk=1.0, staleness=1.0, contradiction_risk=1.0,
    ))
    assert risky < good


def test_utility_can_go_negative():
    u = utility(UtilityFeatures(p_useful=0.1, impact=0.1, privacy_risk=1.0, read_cost=1.0))
    assert u < 0
