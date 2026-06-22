"""Benchmark task specifications.

A :class:`TaskSpec` is a replayable benchmark task: a prompt the agent is given, the
snapshot it runs against, the state assertions that define success, the memory items
it is expected to use, and the rubric that scores it. Tasks are the unit of the
backtest: each runs with and without the compiled knowledge base and is scored the
same way.

A good memory task is one where the answer depends on durable context that is not
reliably inferable from the current app state alone, and where the expected effect of
memory can be judged with explicit evidence. Tasks are stored as YAML so they are
easy to author and review, and loaded into this typed model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from ..ids import content_hash


class ExpectedWrite(BaseModel):
    """A write the agent should make for the task to succeed.

    ``expect`` maps payload fields to required values. A value may be a literal or,
    when authored as ``{"contains": "..."}``, a substring match compiled into a
    predicate by the runner.
    """

    app: str
    action: str
    expect: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class TaskSpec(BaseModel):
    """A replayable benchmark task."""

    task_id: str
    title: str = ""
    prompt: str
    # Bitemporal coordinates of the snapshot the task runs against.
    as_of_valid: str
    as_of_ingest: str
    # The memory the task expects to be used, by claim substring, for retrieval scoring.
    memory_expected: list[str] = Field(default_factory=list)
    # State assertions defining success and forbidden actions.
    expected_writes: list[ExpectedWrite] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    max_writes: int | None = 1
    rubric_id: str = "default"
    # Why this task tests memory, for documentation and review.
    why_memory: str = ""

    @property
    def spec_hash(self) -> str:
        return content_hash(self.model_dump(mode="json"))


def load_task(path: str | Path) -> TaskSpec:
    """Load a single task spec from a YAML file."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return TaskSpec.model_validate(data)


def load_tasks(directory: str | Path) -> list[TaskSpec]:
    """Load all task specs in a directory, sorted by task id for stable ordering."""
    directory = Path(directory)
    tasks = [load_task(p) for p in sorted(directory.glob("*.yaml"))]
    tasks.sort(key=lambda t: t.task_id)
    return tasks
