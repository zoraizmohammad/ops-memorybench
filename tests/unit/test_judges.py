"""Tests for the rubric judges."""

from __future__ import annotations

from datetime import datetime

from ombench.eval.judges import AnthropicJudge, RuleBasedJudge, RunArtifacts, _parse_score
from ombench.eval.tasks import ExpectedWrite, TaskSpec
from ombench.llm.base import LLMResponse
from ombench.replay.sandbox import WriteAction
from ombench.timeutil import UTC

T = datetime(2026, 5, 14, 17, 0, 0, tzinfo=UTC)


def _task():
    return TaskSpec(
        task_id="reschedule",
        prompt="Reschedule my 1:1 with Bob",
        as_of_valid="2026-05-10T00:00:00Z",
        as_of_ingest="2026-06-01T00:00:00Z",
        memory_expected=["prefers afternoons"],
        expected_writes=[ExpectedWrite(app="gcal", action="update_event", expect={"start": "15:00"})],
        forbidden_actions=["delete_event"],
        max_writes=1,
    )


def _w(app, action, payload):
    return WriteAction(app=app, action=action, payload=payload, at=T)


def test_rule_judge_full_marks_with_memory():
    judge = RuleBasedJudge()
    artifacts = RunArtifacts(
        writes=[_w("gcal", "update_event", {"event_id": "ev", "start": "15:00"})],
        retrieved_claims=["user prefers afternoons and avoids Fridays"],
    )
    scores = judge.score(_task(), artifacts)
    assert scores.task_outcome == 1.0
    assert scores.action_validity == 1.0
    assert scores.memory_retrieval > 0.9
    assert scores.memory_application == 1.0
    assert scores.success


def test_rule_judge_without_memory_fails_outcome():
    judge = RuleBasedJudge()
    artifacts = RunArtifacts(
        writes=[_w("gcal", "update_event", {"event_id": "ev", "start": "12:00"})],
        retrieved_claims=[],
    )
    scores = judge.score(_task(), artifacts)
    # Wrong time, so the outcome assertion fails.
    assert scores.task_outcome == 0.0
    assert scores.memory_retrieval == 0.0
    assert scores.memory_application == 0.0
    assert not scores.success


def test_rule_judge_penalizes_forbidden_action():
    judge = RuleBasedJudge()
    artifacts = RunArtifacts(
        writes=[
            _w("gcal", "update_event", {"start": "15:00"}),
            _w("gcal", "delete_event", {}),
        ],
        retrieved_claims=["user prefers afternoons"],
    )
    scores = judge.score(_task(), artifacts)
    assert scores.action_validity == 0.0
    assert not scores.success


def test_rule_judge_penalizes_excess_writes():
    judge = RuleBasedJudge()
    artifacts = RunArtifacts(
        writes=[
            _w("gcal", "update_event", {"start": "15:00"}),
            _w("gcal", "update_event", {"start": "15:00"}),
        ],
        retrieved_claims=["user prefers afternoons"],
    )
    scores = judge.score(_task(), artifacts)
    assert scores.action_validity <= 0.5


def test_contains_predicate_matches():
    task = TaskSpec(
        task_id="announce", prompt="Announce Redwood",
        as_of_valid="2026-05-14T00:00:00Z", as_of_ingest="2026-06-01T00:00:00Z",
        expected_writes=[ExpectedWrite(app="slack", action="post_message",
                                       expect={"text": {"contains": "is live"}})],
    )
    artifacts = RunArtifacts(writes=[_w("slack", "post_message", {"text": "Launch Redwood is live"})],
                             retrieved_claims=[])
    scores = RuleBasedJudge().score(task, artifacts)
    assert scores.task_outcome == 1.0


def test_parse_score():
    assert _parse_score("0.8") == 0.8
    assert _parse_score("The score is 1.0 overall") == 1.0
    # Out of range bare integers are rejected rather than clamped, so a stray 5 is
    # not misread as a perfect score.
    assert _parse_score("clamp 5") is None
    assert _parse_score("no number here") is None
    # An explicit out of 10 phrasing is normalized.
    assert _parse_score("8/10") == 0.8
    assert _parse_score("7 out of 10") == 0.7


def test_anthropic_judge_refines_application():
    class FakeLLM:
        model = "fake"
        price_in = 0.0
        price_out = 0.0

        def complete(self, *, system, messages, tools=None, max_tokens=4096):
            return LLMResponse(text="0.95")

        def cost_usd(self, response):
            return 0.0

    judge = AnthropicJudge(FakeLLM())
    artifacts = RunArtifacts(
        writes=[_w("gcal", "update_event", {"start": "15:00"})],
        retrieved_claims=["user prefers afternoons"],
    )
    scores = judge.score(_task(), artifacts)
    assert scores.memory_application == 0.95
    assert any("refined" in n for n in scores.notes)
