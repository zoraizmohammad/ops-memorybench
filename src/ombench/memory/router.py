"""Namespace routing.

A query is routed to the namespaces most likely to hold relevant memory: the user's
personal preferences, the team's norms, the active project's context, or current app
state. Routing narrows retrieval and supplies the namespace prior used in reranking.

The default router is rule based and deterministic, scoring each namespace from cue
words and any explicit project or person hints in the query. A learned router is a
documented extension that plugs in behind the same interface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import Namespace

_USER_CUES = re.compile(r"\b(?:my|i|me|mine|prefer|preference)\b", re.IGNORECASE)
_TEAM_CUES = re.compile(r"\b(?:we|team|our|norm|convention|announce|policy)\b", re.IGNORECASE)
_PROJECT_CUES = re.compile(r"\b(?:project|launch|milestone|roadmap|release)\b", re.IGNORECASE)
_APP_CUES = re.compile(r"\b(?:channel|calendar|event|document|doc|meeting|schedule)\b", re.IGNORECASE)


@dataclass
class RouteScores:
    """Per namespace routing weights, normalized to sum to one."""

    scores: dict[Namespace, float]

    def top(self, n: int = 2) -> list[Namespace]:
        return [ns for ns, _ in sorted(self.scores.items(), key=lambda x: -x[1])[:n]]

    def prior(self, namespace: Namespace) -> float:
        return self.scores.get(namespace, 0.0)


def route(query: str) -> RouteScores:
    """Score the namespaces for a query.

    Every namespace gets a small base weight so nothing is fully excluded, plus cue
    based boosts. The result is normalized so it can serve directly as a prior.
    """
    raw = {
        Namespace.USER: 0.1 + 0.6 * len(_USER_CUES.findall(query)),
        Namespace.TEAM: 0.1 + 0.6 * len(_TEAM_CUES.findall(query)),
        Namespace.PROJECT: 0.1 + 0.6 * len(_PROJECT_CUES.findall(query)),
        Namespace.APP_STATE: 0.1 + 0.4 * len(_APP_CUES.findall(query)),
    }
    total = sum(raw.values()) or 1.0
    return RouteScores(scores={ns: w / total for ns, w in raw.items()})
