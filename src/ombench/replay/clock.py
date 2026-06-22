"""Replay clock.

The replay sandbox runs against a frozen wall clock so that an agent under test can
never observe time advancing in a way that would make a backtest unfaithful. This
re exports the frozen clock from the time utilities and adds a helper to derive the
replay instant from a snapshot's bitemporal coordinates.
"""

from __future__ import annotations

from datetime import datetime

from ..timeutil import FrozenClock


def clock_for_snapshot(as_of_valid_time: datetime) -> FrozenClock:
    """Return a clock frozen at a snapshot's valid time.

    The agent acting against the sandbox sees this as the current time, matching the
    moment the historical task occurred.
    """
    return FrozenClock(as_of_valid_time)


__all__ = ["FrozenClock", "clock_for_snapshot"]
