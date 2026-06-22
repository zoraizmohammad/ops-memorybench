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
        return round(
            self.task_outcome * self.weights["task_outcome"]
            + self.memory_retrieval * self.weights["memory_retrieval"]
            + self.memory_application * self.weights["memory_application"]
            + self.action_validity * self.weights["action_validity"],
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
    precision = relevant / len(lowered) if lowered else 0.0
    covered = sum(1 for s in subs if any(s in c for c in lowered))
    recall = covered / len(subs)
    return (round(precision, 4), round(recall, 4))
