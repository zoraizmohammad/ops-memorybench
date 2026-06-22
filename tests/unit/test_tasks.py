"""Tests for the task spec schema and loader."""

from __future__ import annotations

from ombench.eval.tasks import ExpectedWrite, TaskSpec, load_task, load_tasks


def _spec():
    return TaskSpec(
        task_id="reschedule_1on1",
        title="Reschedule a recurring 1:1",
        prompt="Reschedule my 1:1 with Bob",
        as_of_valid="2026-05-10T00:00:00Z",
        as_of_ingest="2026-06-01T00:00:00Z",
        memory_expected=["prefers afternoons"],
        expected_writes=[ExpectedWrite(app="gcal", action="update_event", expect={"start": "15:00"})],
        why_memory="The preference is not visible in the calendar snapshot.",
    )


def test_spec_hash_stable():
    assert _spec().spec_hash == _spec().spec_hash


def test_load_task_from_yaml(tmp_path):
    yaml_text = """
task_id: announce_launch
title: Announce launch
prompt: Announce the Redwood launch
as_of_valid: "2026-05-14T00:00:00Z"
as_of_ingest: "2026-06-01T00:00:00Z"
memory_expected:
  - announcements channel
expected_writes:
  - app: slack
    action: post_message
    expect:
      channel: announcements
forbidden_actions:
  - delete_channel
why_memory: The preferred channel is a team norm.
"""
    path = tmp_path / "announce.yaml"
    path.write_text(yaml_text)
    task = load_task(path)
    assert task.task_id == "announce_launch"
    assert task.expected_writes[0].app == "slack"
    assert "announcements channel" in task.memory_expected


def test_load_tasks_sorted(tmp_path):
    for tid in ["b_task", "a_task"]:
        (tmp_path / f"{tid}.yaml").write_text(
            f'task_id: {tid}\nprompt: x\nas_of_valid: "2026-05-10T00:00:00Z"\n'
            f'as_of_ingest: "2026-06-01T00:00:00Z"\n'
        )
    tasks = load_tasks(tmp_path)
    assert [t.task_id for t in tasks] == ["a_task", "b_task"]


def test_defaults():
    t = TaskSpec(task_id="t", prompt="p", as_of_valid="2026-05-10T00:00:00Z",
                 as_of_ingest="2026-06-01T00:00:00Z")
    assert t.max_writes == 1
    assert t.rubric_id == "default"
