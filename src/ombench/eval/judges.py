"""Rubric judges.

A judge takes a completed run (the agent result, the sandbox writes, the retrieved
memory) and the task spec, and produces :class:`RubricScores`. Two judges ship:

- :class:`RuleBasedJudge` is deterministic. It scores outcome and validity from the
  state validators, retrieval from precision and recall against expected memory, and
  application from whether the winning write reflects the expected memory. This is the
  keyless default and is fully reproducible.

- :class:`AnthropicJudge` refines the memory application axis with an LLM, but only
  within strict safeguards: the prompt is rubric grounded and evidence grounded, and
  the judge is blind to which condition (with or without memory) produced the run, to
  avoid the position, verbosity, and self enhancement biases documented for LLM
  judges. It falls back to the rule based score on any error.

The judge separation matters: the rule based judge is enough to run the backtest
reproducibly, while the LLM judge adds nuance on the one axis that benefits from
judgment, with a human auditable subset.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..llm.base import LLMClient, Message, Role
from ..replay.sandbox import WriteAction
from ..replay.validators import StateAssertion, from_assertions, run_validators
from .rubrics import RubricScores, retrieval_scores
from .tasks import TaskSpec


@dataclass
class RunArtifacts:
    """Everything a judge needs about one completed run."""

    writes: list[WriteAction]
    retrieved_claims: list[str]
    final_text: str = ""


def _build_assertions(task: TaskSpec) -> list[StateAssertion]:
    assertions: list[StateAssertion] = []
    for ew in task.expected_writes:
        expect = {}
        for k, v in ew.expect.items():
            if isinstance(v, dict) and "contains" in v:
                needle = str(v["contains"]).lower()
                expect[k] = lambda val, n=needle: isinstance(val, str) and n in val.lower()
            else:
                expect[k] = v
        assertions.append(
            StateAssertion(
                app=ew.app, action=ew.action, expect=expect,
                forbidden_actions=task.forbidden_actions, description=ew.description or ew.action,
            )
        )
    if not assertions and task.forbidden_actions:
        assertions.append(StateAssertion(forbidden_actions=task.forbidden_actions))
    return assertions


class Judge(ABC):
    @abstractmethod
    def score(self, task: TaskSpec, artifacts: RunArtifacts) -> RubricScores:
        raise NotImplementedError


class RuleBasedJudge(Judge):
    """Deterministic rubric judge built on validators and retrieval comparison."""

    def score(self, task: TaskSpec, artifacts: RunArtifacts) -> RubricScores:
        scores = RubricScores()
        assertions = _build_assertions(task)

        # Task outcome: did the expected write happen with the right fields.
        write_validators = from_assertions(assertions) if assertions else []
        results = run_validators(artifacts.writes, write_validators)
        write_made = [r for r in results if r.name not in ("no_forbidden", "single_action")]
        if write_made:
            scores.task_outcome = sum(1.0 for r in write_made if r.passed) / len(write_made)
        else:
            scores.task_outcome = 1.0 if artifacts.writes or not task.expected_writes else 0.0

        # Action validity: no forbidden actions and within the write budget.
        validity = 1.0
        forbidden_hit = any(
            w.action in set(task.forbidden_actions) for w in artifacts.writes
        )
        if forbidden_hit:
            validity = 0.0
            scores.notes.append("forbidden action performed")
        if task.max_writes is not None and len(artifacts.writes) > task.max_writes:
            validity = min(validity, 0.5)
            scores.notes.append(f"{len(artifacts.writes)} writes exceeds {task.max_writes}")
        scores.action_validity = validity

        # Memory retrieval: precision and recall against expected memory, summarized
        # as their harmonic mean (F1) so a single axis reflects both.
        precision, recall = retrieval_scores(artifacts.retrieved_claims, task.memory_expected)
        scores.memory_retrieval = _f1(precision, recall)

        # Memory application: did the achieved outcome reflect the expected memory.
        # If the outcome is correct and the expected memory was retrieved, the agent
        # applied it; if the outcome is wrong, application is zero.
        if not task.memory_expected:
            scores.memory_application = scores.task_outcome
        else:
            scores.memory_application = scores.task_outcome if recall > 0 else 0.0
        return scores


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


class AnthropicJudge(Judge):
    """LLM judge that refines the application axis, with bias safeguards."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self.base = RuleBasedJudge()

    def score(self, task: TaskSpec, artifacts: RunArtifacts) -> RubricScores:
        scores = self.base.score(task, artifacts)
        # Only consult the LLM on the application axis, and only when there is memory
        # to apply and an outcome to interpret. The rule based scores stand otherwise.
        if not task.memory_expected:
            return scores
        try:
            refined = self._judge_application(task, artifacts)
            if refined is not None:
                scores.memory_application = refined
                scores.notes.append("application axis refined by llm judge")
        except Exception:  # pragma: no cover - judge must never break the backtest
            scores.notes.append("llm judge failed, using rule based application score")
        return scores

    def _judge_application(self, task: TaskSpec, artifacts: RunArtifacts) -> float | None:
        # Blind to condition: the prompt never says whether memory was mounted, only
        # presents the evidence and asks for a grounded judgement against the rubric.
        writes_desc = "; ".join(
            f"{w.app}.{w.action}({w.payload})" for w in artifacts.writes
        ) or "no actions taken"
        memory_desc = "; ".join(task.memory_expected)
        system = (
            "You are a strict evaluator. Score, from 0.0 to 1.0, how well the agent's "
            "actions reflect the durable knowledge listed, grounding your score only in "
            "the evidence shown. Respond with a single number between 0 and 1."
        )
        prompt = (
            f"Task: {task.prompt}\n"
            f"Durable knowledge that should inform the action: {memory_desc}\n"
            f"Actions the agent took: {writes_desc}\n"
            "Score (0 to 1):"
        )
        resp = self.llm.complete(system=system, messages=[Message(role=Role.USER, content=prompt)])
        return _parse_score(resp.text)


def _parse_score(text: str) -> float | None:
    import re

    m = re.search(r"(\d?\.\d+|\d)", text)
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    return max(0.0, min(1.0, value))
