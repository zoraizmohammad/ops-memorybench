"""ombench.viz subpackage.

Visualization and trust surfaces: a memory diff viewer, a provenance graph, a human
approval queue, a counterfactual replay explorer, a time travel debugging view, and an
HTML report dashboard. These make the platform legible during a demo and auditable in
production.
"""

from __future__ import annotations

from .approval_queue import ApprovalQueue
from .counterfactual import MemoryPack, explore
from .memory_diff import MemoryDiff, diff_memory
from .provenance import build_provenance, to_dot, to_text
from .report_html import render_html
from .timetravel import entity_timeline, render_timeline_text, workspace_activity

__all__ = [
    "ApprovalQueue",
    "MemoryDiff",
    "MemoryPack",
    "build_provenance",
    "diff_memory",
    "entity_timeline",
    "explore",
    "render_html",
    "render_timeline_text",
    "to_dot",
    "to_text",
    "workspace_activity",
]
