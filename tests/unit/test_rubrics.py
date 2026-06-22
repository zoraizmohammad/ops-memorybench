"""Tests for the four axis rubric."""

from __future__ import annotations

from ombench.eval.rubrics import RubricScores, retrieval_scores


def test_total_is_weighted():
    r = RubricScores(task_outcome=1.0, memory_retrieval=1.0, memory_application=1.0, action_validity=1.0)
    assert r.total == 1.0


def test_partial_total():
    r = RubricScores(task_outcome=1.0, memory_retrieval=0.0, memory_application=0.0, action_validity=1.0)
    # 0.4 outcome + 0.2 validity
    assert r.total == 0.6


def test_success_requires_outcome_and_validity():
    assert RubricScores(task_outcome=1.0, action_validity=1.0).success
    assert not RubricScores(task_outcome=1.0, action_validity=0.5).success
    assert not RubricScores(task_outcome=0.5, action_validity=1.0).success


def test_as_dict():
    d = RubricScores(task_outcome=1.0, action_validity=1.0).as_dict()
    assert d["success"] == 1.0
    assert "total" in d


def test_retrieval_perfect():
    p, r = retrieval_scores(["user prefers afternoons"], ["prefers afternoons"])
    assert p == 1.0
    assert r == 1.0


def test_retrieval_recall_miss():
    p, r = retrieval_scores(["something unrelated"], ["prefers afternoons"])
    assert r == 0.0


def test_retrieval_precision_with_noise():
    p, r = retrieval_scores(["prefers afternoons", "noise one", "noise two"], ["prefers afternoons"])
    # One of three retrieved is relevant (rounded to 4 decimals).
    assert abs(p - 1 / 3) < 1e-3
    assert r == 1.0


def test_retrieval_vacuous_when_no_expectation():
    assert retrieval_scores(["anything"], []) == (1.0, 1.0)


def test_retrieval_empty_retrieval():
    p, r = retrieval_scores([], ["prefers afternoons"])
    assert p == 0.0
    assert r == 0.0
