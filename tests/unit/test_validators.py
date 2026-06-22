"""Tests for state diff validators."""

from __future__ import annotations

from datetime import datetime

from ombench.replay.sandbox import WriteAction
from ombench.replay.validators import (
    StateAssertion,
    check_no_forbidden,
    check_single_action,
    check_write_made,
    from_assertions,
    run_validators,
)
from ombench.timeutil import UTC

T = datetime(2026, 5, 14, 17, 0, 0, tzinfo=UTC)


def _w(app, action, payload):
    return WriteAction(app=app, action=action, payload=payload, at=T)


def test_check_write_made_literal():
    writes = [_w("gcal", "update_event", {"event_id": "ev1", "start": "15:00"})]
    a = StateAssertion(app="gcal", action="update_event", expect={"start": "15:00"})
    assert check_write_made(writes, a).passed


def test_check_write_made_predicate():
    writes = [_w("slack", "post_message", {"channel": "C_ANNOUNCE", "text": "Launch Redwood is live"})]
    a = StateAssertion(app="slack", action="post_message",
                       expect={"text": lambda t: "is live" in t})
    assert check_write_made(writes, a).passed


def test_check_write_made_fails_on_wrong_value():
    writes = [_w("gcal", "update_event", {"start": "12:00"})]
    a = StateAssertion(app="gcal", action="update_event", expect={"start": "15:00"})
    result = check_write_made(writes, a)
    assert not result.passed


def test_check_write_made_fails_when_absent():
    a = StateAssertion(app="gcal", action="update_event", expect={"start": "15:00"})
    assert not check_write_made([], a).passed


def test_check_no_forbidden():
    writes = [_w("slack", "post_message", {})]
    a = StateAssertion(forbidden_actions=["delete_channel"])
    assert check_no_forbidden(writes, a).passed
    bad = [_w("slack", "delete_channel", {})]
    assert not check_no_forbidden(bad, a).passed


def test_check_single_action():
    one = [_w("slack", "post_message", {})]
    assert check_single_action(one, max_writes=1).passed
    two = [_w("slack", "post_message", {}), _w("slack", "post_message", {})]
    assert not check_single_action(two, max_writes=1).passed


def test_from_assertions_builds_validators():
    a = StateAssertion(app="gcal", action="update_event", expect={"start": "15:00"},
                       forbidden_actions=["delete_event"])
    validators = from_assertions([a], max_writes=1)
    writes = [_w("gcal", "update_event", {"start": "15:00"})]
    results = run_validators(writes, validators)
    assert all(r.passed for r in results)
    assert len(results) == 3  # write-made, no-forbidden, single-action
