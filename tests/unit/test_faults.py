"""Tests for fault injection."""

from __future__ import annotations

from ombench.replay.faults import Fault, FaultInjector
from ombench.traces.schema import AppRef


def base_executor(name, args):
    return {"ok": True}, [AppRef(app="gcal", entity_type="event", entity_id="e", role="write")]


def test_no_faults_passes_through():
    inj = FaultInjector(faults=[])
    result, refs = inj.wrap(base_executor)("gcal.update_event", {})
    assert result["ok"]
    assert refs


def test_error_fault_fires_on_nth_call():
    inj = FaultInjector(faults=[Fault(tool="t", on_call=2, kind="error")])
    wrapped = inj.wrap(base_executor)
    first, _ = wrapped("t", {})
    assert first["ok"]  # first call ok
    second, _ = wrapped("t", {})
    assert second["error"] == "tool_failed"  # second call faults


def test_rate_limit_fault():
    inj = FaultInjector(faults=[Fault(tool="t", on_call=1, kind="rate_limit")])
    result, _ = inj.wrap(base_executor)("t", {})
    assert result["error"] == "rate_limited"
    assert result["retry_after"] == 1


def test_stale_and_empty_faults():
    inj = FaultInjector(faults=[Fault(tool="t", on_call=1, kind="stale")])
    result, _ = inj.wrap(base_executor)("t", {})
    assert result["stale"]

    inj2 = FaultInjector(faults=[Fault(tool="t", on_call=1, kind="empty")])
    result2, _ = inj2.wrap(base_executor)("t", {})
    assert result2["result"] is None


def test_fault_applies_to_any_tool_when_tool_none():
    inj = FaultInjector(faults=[Fault(tool=None, on_call=1, kind="error")])
    result, _ = inj.wrap(base_executor)("anything", {})
    assert result["error"] == "tool_failed"


def test_deterministic_across_runs():
    def run():
        inj = FaultInjector(faults=[Fault(tool="t", on_call=2, kind="error")])
        wrapped = inj.wrap(base_executor)
        return [wrapped("t", {})[0] for _ in range(3)]

    assert run() == run()
