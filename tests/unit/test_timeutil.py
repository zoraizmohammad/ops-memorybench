"""Tests for time utilities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ombench.timeutil import (
    UTC,
    Clock,
    FrozenClock,
    ensure_utc,
    from_epoch,
    from_iso,
    to_epoch,
    to_iso,
    utcnow,
)


def test_utcnow_is_aware_utc():
    now = utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_ensure_utc_assumes_naive_is_utc():
    naive = datetime(2026, 5, 14, 12, 0, 0)
    assert ensure_utc(naive).tzinfo == UTC


def test_ensure_utc_converts_other_zones():
    eastern = timezone(timedelta(hours=-5))
    dt = datetime(2026, 5, 14, 12, 0, 0, tzinfo=eastern)
    converted = ensure_utc(dt)
    assert converted.hour == 17
    assert converted.tzinfo == UTC


def test_iso_round_trip():
    dt = datetime(2026, 5, 14, 17, 30, 15, 123000, tzinfo=UTC)
    text = to_iso(dt)
    assert text == "2026-05-14T17:30:15.123Z"
    assert from_iso(text) == dt


def test_from_iso_accepts_offset_and_z():
    a = from_iso("2026-05-14T17:00:00Z")
    b = from_iso("2026-05-14T12:00:00-05:00")
    assert a == b


def test_epoch_round_trip():
    dt = datetime(2026, 5, 14, 17, 0, 0, tzinfo=UTC)
    epoch = to_epoch(dt)
    assert from_epoch(epoch) == dt


def test_slack_style_epoch_parses():
    # Slack message ts is epoch seconds with a microsecond suffix.
    dt = from_epoch("1715706000.000200")
    assert dt.tzinfo == UTC


def test_default_clock_advances():
    clock = Clock()
    assert isinstance(clock.now(), datetime)


def test_frozen_clock_is_constant():
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FrozenClock(instant)
    assert clock.now() == instant
    assert clock.now() == instant
    assert clock.instant == instant


def test_frozen_clock_can_step():
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    clock.set(datetime(2026, 6, 1, tzinfo=UTC))
    assert clock.now() == datetime(2026, 6, 1, tzinfo=UTC)


def test_frozen_clock_coerces_naive():
    clock = FrozenClock(datetime(2026, 1, 1))
    assert clock.now().tzinfo == UTC
