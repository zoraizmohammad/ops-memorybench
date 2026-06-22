"""ombench.replay subpackage.

The deterministic simulated environment. A :class:`Sandbox` is seeded from a snapshot;
:class:`SandboxToolRouter` exposes the SaaS tool surface the agent acts against;
:mod:`validators` check the resulting writes; :mod:`faults` injects controlled
failures for resilience testing.
"""

from __future__ import annotations

from .clock import FrozenClock, clock_for_snapshot
from .faults import Fault, FaultInjector
from .sandbox import Sandbox, WriteAction
from .sandbox_api import ALL_TOOLS, SandboxToolRouter
from .validators import (
    StateAssertion,
    ValidationResult,
    from_assertions,
    run_validators,
)

__all__ = [
    "ALL_TOOLS",
    "Fault",
    "FaultInjector",
    "FrozenClock",
    "Sandbox",
    "SandboxToolRouter",
    "StateAssertion",
    "ValidationResult",
    "WriteAction",
    "clock_for_snapshot",
    "from_assertions",
    "run_validators",
]
