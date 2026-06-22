"""Tests for the visualization and trust surface extensions."""

from __future__ import annotations

from datetime import datetime

from ombench.eval.rubrics import RubricScores
from ombench.eval.runner import BacktestReport, ConditionResult, TaskResult
from ombench.memory.resolver import resolve_pair
from ombench.memory.schema import EvidenceRef, MemoryItem, MemoryType, Namespace
from ombench.memory.store import MemoryStore
from ombench.storage import open_memory_store
from ombench.timeutil import UTC
from ombench.viz.approval_queue import ApprovalQueue
from ombench.viz.memory_diff import diff_memory
from ombench.viz.provenance import build_provenance, to_dot, to_text
from ombench.viz.report_html import render_html


def _item(claim, conf=0.5, active=True, subject="Alice"):
    return MemoryItem(type=MemoryType.SEMANTIC, namespace=Namespace.USER, subject=subject,
                      claim=claim, confidence=conf, active=active,
                      created_at=datetime(2026, 5, 1, tzinfo=UTC))


# -- memory diff ---------------------------------------------------------


def test_memory_diff_added_and_removed():
    a = _item("prefers afternoons")
    before = [a]
    after = [a, _item("avoids Fridays", subject="Alice")]
    diff = diff_memory(before, after)
    assert len(diff.added) == 1
    assert diff.unchanged == 1
    assert "Added" in diff.to_markdown()


def test_memory_diff_deactivation():
    active = _item("prefers mornings", active=True)
    deactivated = MemoryItem(memory_id=active.memory_id, type=MemoryType.SEMANTIC,
                             namespace=Namespace.USER, subject="Alice",
                             claim="prefers mornings", active=False,
                             created_at=datetime(2026, 5, 1, tzinfo=UTC))
    diff = diff_memory([active], [deactivated])
    assert len(diff.removed) == 1


# -- provenance ----------------------------------------------------------


def test_provenance_node_and_text():
    s = open_memory_store()
    ms = MemoryStore(s)
    item = MemoryItem(type=MemoryType.SEMANTIC, namespace=Namespace.USER, subject="Alice",
                      claim="prefers afternoons",
                      evidence=[EvidenceRef(kind="trace", ref="trace_1")])
    ms.add(item)
    node = build_provenance(ms, item.memory_id)
    assert node.evidence == ["trace:trace_1"]
    assert "prefers afternoons" in to_text(node)
    s.close()


def test_provenance_dot_includes_edges():
    s = open_memory_store()
    ms = MemoryStore(s)
    a = _item("prefers mornings", conf=0.4)
    b = _item("prefers not mornings", conf=0.8)
    ms.add(a)
    ms.add(b)
    resolve_pair(ms, a, b)
    dot = to_dot(ms)
    assert "digraph provenance" in dot
    assert "supersedes" in dot
    s.close()


# -- approval queue ------------------------------------------------------


def test_approval_queue_routing():
    s = open_memory_store()
    q = ApprovalQueue(s)
    assert q.needs_review(confidence=0.6, acl="team")  # mid confidence
    assert not q.needs_review(confidence=0.95, acl="team")  # auto accept
    assert q.needs_review(confidence=0.99, acl="personal")  # personal always reviewed
    s.close()


def test_approval_queue_enqueue_and_decide():
    s = open_memory_store()
    q = ApprovalQueue(s)
    aid = q.enqueue(claim="prefers afternoons", namespace="user", confidence=0.6, acl="personal")
    assert len(q.pending()) == 1
    q.decide(aid, approved=True)
    assert q.pending() == []
    assert len(q.approved()) == 1
    s.close()


def test_approval_queue_idempotent_enqueue():
    s = open_memory_store()
    q = ApprovalQueue(s)
    q.enqueue(claim="x", namespace="user", confidence=0.6, acl="personal")
    q.enqueue(claim="x", namespace="user", confidence=0.6, acl="personal")
    assert len(q.pending()) == 1
    s.close()


# -- html report ---------------------------------------------------------


def _report():
    def cond(c, outcome):
        return ConditionResult(condition=c, scores=RubricScores(task_outcome=outcome, action_validity=1.0),
                               retrieved_claims=[], writes=[], final_text="", input_tokens=1,
                               output_tokens=1, cost_usd=0.0)
    return BacktestReport(results=[
        TaskResult("t1", without_memory=cond("without_memory", 0.0), with_memory=cond("with_memory", 1.0)),
    ])


def test_render_html():
    html = render_html(_report())
    assert "<!doctype html>" in html
    assert "with memory" in html
    assert "t1" in html
    assert "Wilcoxon" in html
