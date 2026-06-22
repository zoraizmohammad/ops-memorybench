"""Integration test of the full replay loop.

Materializes a snapshot from synced fixtures, seeds a sandbox from it, runs the agent
against the sandbox tool surface with and without memory, and validates the resulting
writes. This exercises the whole Phase 6 stack together and is the spine of the
backtest assembled in Phase 7.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ombench.events.store import EventStore
from ombench.integrations.gcal.sync import GCalSync
from ombench.integrations.slack.sync import SlackSync
from ombench.llm.agent import OperationalAgent
from ombench.llm.stub import StubLLM
from ombench.replay.faults import Fault, FaultInjector
from ombench.replay.sandbox import Sandbox
from ombench.replay.sandbox_api import SandboxToolRouter
from ombench.replay.validators import StateAssertion, from_assertions, run_validators
from ombench.snapshots import SnapshotMaterializer
from ombench.storage import open_store
from ombench.timeutil import UTC, FrozenClock, from_iso

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def seeded_state(config):
    store = open_store(config)
    es = EventStore(store.backend, store.blobs)
    clock = FrozenClock(datetime(2026, 5, 14, 18, 0, 0, tzinfo=UTC))
    SlackSync(es, clock=clock, fixtures_path=FIXTURES / "slack" / "workspace.json").run_sync()
    GCalSync(es, clock=clock, fixtures_path=FIXTURES / "gcal" / "calendar.json").run_sync()
    # Snapshot as of before the 1:1 reschedule so the agent must decide the time.
    mat = SnapshotMaterializer(store)
    snap = mat.materialize(
        as_of_valid=from_iso("2026-05-10T00:00:00Z"),
        as_of_ingest=from_iso("2026-06-01T00:00:00Z"),
        persist=False,
    )
    state = {
        f"{e.app}/{e.entity_type}/{e.entity_id}": {
            "payload": store_state(mat, snap, e),
            "edges": {}, "deleted": e.deleted,
        }
        for e in snap.entities
    }
    yield state
    store.close()


def store_state(mat, snap, entity):
    # Re-materialize the persisted full state lookup; for the non persisted snapshot
    # we rebuild payloads from the materializer's event store directly.
    es = mat.events
    materialized = es.materialize_entity(entity.app, entity.entity_type, entity.entity_id,
                                         as_of_valid=snap.as_of_valid_time,
                                         as_of_ingest=snap.as_of_ingest_time)
    return materialized.payload if materialized else {}


def _run(state, *, with_memory: bool):
    sandbox = Sandbox(state, as_of=from_iso("2026-05-10T00:00:00Z"))
    router = SandboxToolRouter(sandbox)
    memory = "# Relevant memory\n- user prefers afternoons and avoids Fridays" if with_memory else None
    agent = OperationalAgent(
        StubLLM(), tools=router.tools(), tool_executor=router.execute, memory_text=memory,
    )
    agent.run("Reschedule my 1:1 with Bob")
    return sandbox


def test_replay_with_memory_picks_afternoon(seeded_state):
    sandbox = _run(seeded_state, with_memory=True)
    writes = sandbox.writes_for("gcal")
    assert writes
    assert writes[0].payload["start"] == "15:00"


def test_replay_without_memory_picks_default(seeded_state):
    sandbox = _run(seeded_state, with_memory=False)
    writes = sandbox.writes_for("gcal")
    assert writes[0].payload["start"] == "12:00"


def test_validators_pass_with_memory(seeded_state):
    sandbox = _run(seeded_state, with_memory=True)
    assertion = StateAssertion(
        app="gcal", action="update_event", expect={"start": "15:00"},
        forbidden_actions=["delete_event"], description="reschedule to afternoon",
    )
    results = run_validators(sandbox.writes, from_assertions([assertion], max_writes=1))
    assert all(r.passed for r in results)


def test_validators_fail_without_memory(seeded_state):
    sandbox = _run(seeded_state, with_memory=False)
    assertion = StateAssertion(app="gcal", action="update_event", expect={"start": "15:00"})
    results = run_validators(sandbox.writes, from_assertions([assertion]))
    assert not all(r.passed for r in results)


def test_fault_injection_makes_tool_fail(seeded_state):
    sandbox = Sandbox(seeded_state, as_of=from_iso("2026-05-10T00:00:00Z"))
    router = SandboxToolRouter(sandbox)
    injector = FaultInjector(faults=[Fault(tool="gcal.update_event", on_call=1, kind="error")])
    executor = injector.wrap(router.execute)
    result, refs = executor("gcal.update_event", {"event_id": "ev_1on1_bob", "start": "15:00"})
    assert result.get("error") == "tool_failed"
    # The faulted write did not reach the sandbox log.
    assert sandbox.writes_for("gcal") == []
