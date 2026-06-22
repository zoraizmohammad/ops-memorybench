"""Counterfactual replay explorer.

Lets you compare alternate retrieved memory packs for the same task: what would the
agent have done if it had been given memory pack A versus pack B? This turns the
backtest's binary with versus without comparison into a richer exploration of which
specific memories drive the outcome, which is invaluable for understanding and
debugging the retrieval policy.

Each counterfactual runs the agent against the same seeded sandbox with a different
mounted memory pack and reports the resulting writes and rubric, so packs can be
ranked head to head.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..eval.judges import Judge, RuleBasedJudge, RunArtifacts
from ..eval.rubrics import RubricScores
from ..eval.tasks import TaskSpec
from ..llm.agent import OperationalAgent
from ..llm.base import LLMClient
from ..replay.sandbox import Sandbox
from ..replay.sandbox_api import SandboxToolRouter
from ..timeutil import from_iso


@dataclass
class MemoryPack:
    """A named set of memory claims to mount for a counterfactual."""

    name: str
    claims: list[str] = field(default_factory=list)


@dataclass
class CounterfactualResult:
    pack: str
    scores: RubricScores
    writes: list[dict]


def _format(claims: list[str]) -> str | None:
    if not claims:
        return None
    return "# Relevant memory\n\n" + "\n".join(f"- {c}" for c in claims)


def explore(
    task: TaskSpec,
    state: dict,
    packs: list[MemoryPack],
    *,
    llm: LLMClient,
    judge: Judge | None = None,
) -> list[CounterfactualResult]:
    """Run the task under each memory pack and return ranked results.

    All runs share the same seeded snapshot, so the only difference between them is the
    mounted memory pack, isolating its causal effect.
    """
    judge = judge or RuleBasedJudge()
    results: list[CounterfactualResult] = []
    for pack in packs:
        sandbox = Sandbox(state, as_of=from_iso(task.as_of_valid))
        router = SandboxToolRouter(sandbox)
        agent = OperationalAgent(
            llm, tools=router.tools(), tool_executor=router.execute,
            memory_text=_format(pack.claims),
        )
        agent.run(task.prompt, task_ref=task.task_id)
        artifacts = RunArtifacts(writes=sandbox.writes, retrieved_claims=pack.claims)
        scores = judge.score(task, artifacts)
        results.append(CounterfactualResult(
            pack=pack.name, scores=scores,
            writes=[{"app": w.app, "action": w.action, "payload": w.payload} for w in sandbox.writes],
        ))
    results.sort(key=lambda r: -r.scores.total)
    return results
