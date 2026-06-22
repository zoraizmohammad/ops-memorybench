"""Fault injection for replay contracts.

Inspired by trace assurance work on deterministic replay with structured fault
injection, this wraps a sandbox tool router so that selected tool calls fail in a
controlled, reproducible way: a tool error, a rate limit, an empty or stale read.
Injecting faults lets the backtest probe whether memory helps the agent recover from
failures it has seen before, and whether the agent's side effects stay valid under
adverse conditions.

Faults are deterministic: a fault fires on the Nth matching call, configured up front,
so a replay is exactly reproducible.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..traces.schema import AppRef


@dataclass
class Fault:
    """A controlled failure to inject on a tool call.

    ``tool`` names the tool the fault applies to (or ``None`` for any). ``on_call``
    is the 1 based occurrence index of the matching call that should fail. ``kind``
    selects the failure shape.
    """

    tool: str | None = None
    on_call: int = 1
    kind: str = "error"  # error | rate_limit | empty | stale


@dataclass
class FaultInjector:
    """Wraps a tool executor and injects configured faults deterministically."""

    faults: list[Fault] = field(default_factory=list)
    _counts: dict[str, int] = field(default_factory=dict)

    def wrap(
        self, executor: Callable[[str, dict[str, Any]], tuple[Any, list[AppRef]]]
    ) -> Callable[[str, dict[str, Any]], tuple[Any, list[AppRef]]]:
        """Return an executor that applies faults then delegates to the real one."""

        def wrapped(name: str, args: dict[str, Any]):
            self._counts[name] = self._counts.get(name, 0) + 1
            fault = self._match(name, self._counts[name])
            if fault is not None:
                return self._apply(fault, name), []
            return executor(name, args)

        return wrapped

    def _match(self, name: str, count: int) -> Fault | None:
        for fault in self.faults:
            if (fault.tool is None or fault.tool == name) and fault.on_call == count:
                return fault
        return None

    def _apply(self, fault: Fault, name: str) -> dict[str, Any]:
        if fault.kind == "rate_limit":
            return {"error": "rate_limited", "retry_after": 1, "tool": name}
        if fault.kind == "empty":
            return {"result": None, "note": "empty result injected"}
        if fault.kind == "stale":
            return {"stale": True, "note": "stale read injected"}
        return {"error": "tool_failed", "tool": name}

    def triggered(self) -> int:
        """How many distinct faults could fire given the calls seen so far."""
        return sum(
            1
            for f in self.faults
            if self._counts.get(f.tool or "", 0) >= f.on_call
            or (f.tool is None and any(c >= f.on_call for c in self._counts.values()))
        )
