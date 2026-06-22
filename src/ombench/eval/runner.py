"""Paired backtest runner.

For each benchmark task this runs the agent twice against the same seeded snapshot,
once with the compiled knowledge base mounted and once without, holding the task,
snapshot, and sandbox deterministic. Both runs are scored on the same rubric and the
paired delta is what the backtest reports. This is the measurement the whole platform
exists to make: under identical historical conditions, does the compiled memory
improve the agent.

The runner is provider neutral: with the stub LLM the whole thing is deterministic and
keyless; with the Anthropic client the same protocol runs against a real model, and
repeated runs per condition can be averaged to handle stochasticity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..llm import build_llm
from ..llm.agent import OperationalAgent
from ..llm.base import LLMClient
from ..memory.retriever import MemoryRetriever
from ..memory.store import MemoryStore
from ..replay.sandbox import Sandbox
from ..replay.sandbox_api import SandboxToolRouter
from ..snapshots import SnapshotMaterializer
from ..storage import Store
from ..timeutil import from_iso
from .judges import Judge, RuleBasedJudge, RunArtifacts
from .rubrics import RubricScores
from .tasks import TaskSpec

CONDITIONS = ("without_memory", "with_memory")


@dataclass
class ConditionResult:
    """The outcome of one task under one condition."""

    condition: str
    scores: RubricScores
    retrieved_claims: list[str]
    writes: list[dict[str, Any]]
    final_text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class TaskResult:
    """Paired results for one task across both conditions."""

    task_id: str
    without_memory: ConditionResult
    with_memory: ConditionResult

    @property
    def total_delta(self) -> float:
        return round(self.with_memory.scores.total - self.without_memory.scores.total, 4)


@dataclass
class BacktestReport:
    """The full set of paired task results."""

    results: list[TaskResult] = field(default_factory=list)

    def deltas(self) -> list[float]:
        return [r.total_delta for r in self.results]

    def win_rate(self) -> float:
        if not self.results:
            return 0.0
        wins = sum(1 for r in self.results if r.total_delta > 0)
        return round(wins / len(self.results), 4)


class BacktestRunner:
    """Runs the paired with vs without memory backtest over a task set."""

    def __init__(
        self,
        store: Store,
        *,
        llm: LLMClient | None = None,
        judge: Judge | None = None,
    ) -> None:
        self.store = store
        self.llm = llm or build_llm()
        self.judge = judge or RuleBasedJudge()
        self.materializer = SnapshotMaterializer(store)
        self.retriever = MemoryRetriever(MemoryStore(store))

    def run_task(self, task: TaskSpec) -> TaskResult:
        """Run one task under both conditions and judge each."""
        state = self._seed_state(task)
        retrieved = self._retrieve(task)

        without = self._run_condition(task, state, memory_claims=[], retrieved=[])
        with_mem = self._run_condition(task, state, memory_claims=retrieved, retrieved=retrieved)
        return TaskResult(task_id=task.task_id, without_memory=without, with_memory=with_mem)

    def run(self, tasks: list[TaskSpec]) -> BacktestReport:
        report = BacktestReport()
        for task in tasks:
            report.results.append(self.run_task(task))
        return report

    # -- internals --------------------------------------------------------

    def _seed_state(self, task: TaskSpec) -> dict[str, Any]:
        valid = from_iso(task.as_of_valid)
        ingest = from_iso(task.as_of_ingest)
        snap = self.materializer.materialize(
            as_of_valid=valid, as_of_ingest=ingest, persist=False
        )
        events = self.materializer.events
        state: dict[str, Any] = {}
        for e in snap.entities:
            materialized = events.materialize_entity(
                e.app, e.entity_type, e.entity_id, as_of_valid=valid, as_of_ingest=ingest
            )
            payload = materialized.payload if materialized else {}
            edges = (
                {k: sorted(v) for k, v in materialized.edges.items()} if materialized else {}
            )
            state[f"{e.app}/{e.entity_type}/{e.entity_id}"] = {
                "payload": payload, "edges": edges, "deleted": e.deleted,
            }
        return state

    def _retrieve(self, task: TaskSpec) -> list[str]:
        bundle = self.retriever.retrieve(task.prompt, top_k=5)
        return [r.item.claim for r in bundle.items]

    def _run_condition(
        self,
        task: TaskSpec,
        state: dict[str, Any],
        *,
        memory_claims: list[str],
        retrieved: list[str],
    ) -> ConditionResult:
        sandbox = Sandbox(state, as_of=from_iso(task.as_of_valid))
        router = SandboxToolRouter(sandbox)
        memory_text = self._format_memory(memory_claims) if memory_claims else None
        agent = OperationalAgent(
            self.llm, tools=router.tools(), tool_executor=router.execute, memory_text=memory_text,
        )
        result = agent.run(task.prompt, task_ref=task.task_id)
        artifacts = RunArtifacts(
            writes=sandbox.writes, retrieved_claims=retrieved, final_text=result.final_text
        )
        scores = self.judge.score(task, artifacts)
        condition = "with_memory" if memory_claims else "without_memory"
        return ConditionResult(
            condition=condition,
            scores=scores,
            retrieved_claims=retrieved,
            writes=[{"app": w.app, "action": w.action, "payload": w.payload} for w in sandbox.writes],
            final_text=result.final_text,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
        )

    def _format_memory(self, claims: list[str]) -> str:
        lines = ["# Relevant memory", ""]
        lines += [f"- {c}" for c in claims]
        return "\n".join(lines)
