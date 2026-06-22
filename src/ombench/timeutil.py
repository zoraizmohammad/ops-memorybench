"""Time utilities for a bitemporal system.

Every timestamp in ombench is an aware UTC ``datetime``. The whole platform reads
"now" through :class:`Clock` rather than calling :func:`datetime.now` directly, so
that replay and tests can freeze the wall clock. This is the operational backbone
of deterministic backtesting: a frozen clock plus a bitemporal event log means a
run can only ever see information that had been ingested by a chosen time.
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = [
    "UTC",
    "Clock",
    "FrozenClock",
    "ensure_utc",
    "from_epoch",
    "from_iso",
    "to_epoch",
    "to_iso",
    "utcnow",
]

# ISO 8601 with a trailing Z is the canonical wire format for timestamps.
_ISO_Z = "%Y-%m-%dT%H:%M:%S.%fZ"


def utcnow() -> datetime:
    """Return the current time as an aware UTC datetime.

    Prefer a :class:`Clock` instance in code paths that need to be replayable.
    This free function exists for top level entrypoints where freezing is not
    required.
    """
    return datetime.now(tz=UTC)


def ensure_utc(dt: datetime) -> datetime:
    """Return ``dt`` as an aware UTC datetime.

    Naive datetimes are assumed to already be UTC. Aware datetimes in other zones
    are converted. This keeps every comparison in the event log apples to apples.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_iso(dt: datetime) -> str:
    """Serialize a datetime to a canonical ISO 8601 UTC string with millis."""
    dt = ensure_utc(dt)
    # Trim microseconds to milliseconds for a stable, compact representation.
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def from_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    Accepts a trailing ``Z`` or an explicit offset, with or without fractional
    seconds. This is intentionally permissive because timestamps arrive from many
    SaaS APIs with slightly different shapes.
    """
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        # Fall back to the strict millisecond format.
        dt = datetime.strptime(value, _ISO_Z).replace(tzinfo=UTC)
    return ensure_utc(dt)


def from_epoch(seconds: float) -> datetime:
    """Convert a Unix epoch in seconds (float ok) to an aware UTC datetime.

    Slack timestamps such as ``"1715692800.000200"`` are epoch seconds with a
    microsecond style suffix and parse cleanly through ``float``.
    """
    return datetime.fromtimestamp(float(seconds), tz=UTC)


def to_epoch(dt: datetime) -> float:
    """Convert an aware datetime to a Unix epoch in seconds."""
    return ensure_utc(dt).timestamp()


class Clock:
    """A source of the current time.

    The default clock reads the real wall clock. :class:`FrozenClock` returns a
    fixed instant, which the replay sandbox uses so that an agent under test can
    never observe time advancing in a way that would make a backtest unfaithful.
    """

    def now(self) -> datetime:
        return utcnow()


class FrozenClock(Clock):
    """A clock pinned to a fixed instant.

    Parameters
    ----------
    instant:
        The instant returned by every call to :meth:`now`. Coerced to aware UTC.
    """

    def __init__(self, instant: datetime) -> None:
        self._instant = ensure_utc(instant)

    @property
    def instant(self) -> datetime:
        return self._instant

    def now(self) -> datetime:
        return self._instant

    def set(self, instant: datetime) -> None:
        """Move the frozen instant. Used by replay to step a scenario forward."""
        self._instant = ensure_utc(instant)
