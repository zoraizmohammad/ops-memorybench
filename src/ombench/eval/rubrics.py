"""Four axis rubric.

A run is scored on four separate axes rather than one monolithic number, because that
decomposition makes ablations interpretable: a run can fail because it retrieved
nothing, retrieved the wrong memory, applied the right memory badly, or executed
invalid actions. The axes are:

- **task outcome correctness**: did the agent achieve the task's expected end state
- **memory retrieval correctness**: did it retrieve the memory the task expected
  (precision and recall over expected memory)
- **memory application correctness**: did the action actually reflect that memory
- **action validity and side effect safety**: were the writes valid and in scope

Each axis is a 0..1 score; the rubric also reports a weighted total and a boolean
success. Scores come from the deterministic validators (outcome, validity) and from
retrieval comparison (retrieval, application), with an optional LLM judge refining the
application axis when a live model is available.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RubricScores:
    """Scores on the four axes plus the derived total and success flag."""

    task_outcome: float = 0.0
    memory_retrieval: float = 0.0
    memory_application: float = 0.0
    action_validity: float = 0.0
    notes: list[str] = field(default_factory=list)

    # Axis weights. Outcome and validity dominate; the memory axes are diagnostic.
    weights = {
        "task_outcome": 0.4,
        "memory_retrieval": 0.2,
        "memory_application": 0.2,
        "action_validity": 0.2,
    }

    @property
    def total(self) -> float:
        """The full four axis weighted score, for the diagnostic per task table.

        This is NOT the basis of the paired delta. The two memory axes are zero for
        the without memory condition by experimental construction (it retrieves
        nothing), so a delta computed on this total would be inflated regardless of
        whether memory changed what the agent did. Use :attr:`outcome_score` for the
        paired comparison; this stays as a complete diagnostic view.
        """
        return round(
            self.task_outcome * self.weights["task_outcome"]
            + self.memory_retrieval * self.weights["memory_retrieval"]
            + self.memory_application * self.weights["memory_application"]
            + self.action_validity * self.weights["action_validity"],
            4,
        )

    @property
    def outcome_score(self) -> float:
        """The outcome grounded score used for the paired backtest comparison.

        Only the two axes that measure agent performance, task outcome and action
        validity, renormalized to 0..1. This is fair to compare across conditions
        because neither axis is structurally pinned by whether memory was mounted, so
        any delta reflects a real change in what the agent did, not the experiment
        setup. The memory retrieval and application axes remain diagnostic.
        """
        w = self.weights["task_outcome"] + self.weights["action_validity"]
        return round(
            (self.task_outcome * self.weights["task_outcome"]
             + self.action_validity * self.weights["action_validity"]) / w,
            4,
        )

    @property
    def success(self) -> bool:
        """A run succeeds when the outcome is achieved and actions are valid."""
        return self.task_outcome >= 0.999 and self.action_validity >= 0.999

    def as_dict(self) -> dict[str, float]:
        return {
            "task_outcome": self.task_outcome,
            "memory_retrieval": self.memory_retrieval,
            "memory_application": self.memory_application,
            "action_validity": self.action_validity,
            "total": self.total,
            "outcome_score": self.outcome_score,
            "success": 1.0 if self.success else 0.0,
        }


def retrieval_scores(retrieved_claims: list[str], expected_substrings: list[str]) -> tuple[float, float]:
    """Compute memory retrieval precision and recall against expected substrings.

    A retrieved claim counts as relevant if it contains any expected substring; an
    expected substring counts as covered if any retrieved claim contains it. Returns
    (precision, recall). With no expectations, retrieval is vacuously perfect.
    """
    if not expected_substrings:
        return (1.0, 1.0)
    lowered = [c.lower() for c in retrieved_claims]
    subs = [s.lower() for s in expected_substrings]

    relevant = sum(1 for c in lowered if any(s in c for s in subs))
    covered = sum(1 for s in subs if any(s in c for c in lowered))
    recall = covered / len(subs)
    # Precision is the fraction of relevant items among the retrieved items that
    # could plausibly be relevant, capped by the number of expected items. Dividing
    # by the full retrieved set would pin precision at relevant/top_k regardless of
    # retrieval quality, since a fixed top_k bundle always carries extra context.
    denom = min(len(lowered), len(subs)) if lowered else 0
    precision = relevant / denom if denom else 0.0
    precision = min(1.0, precision)
    return (round(precision, 4), round(recall, 4))
