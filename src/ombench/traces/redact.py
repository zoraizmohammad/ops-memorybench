"""Redaction and PII tagging for captured trajectories.

Trajectories inevitably contain sensitive operational data, so capture is privacy
first: payloads are scanned and redacted before they are stored, and what was
removed is recorded on the span so the posture is auditable. The redactor walks
arbitrary nested structures and replaces matches with a typed placeholder such as
``[REDACTED_EMAIL]``.

The default patterns cover the common cases (emails, phone numbers, secrets and
tokens, credit card like numbers). Callers can extend or replace the rule set. This
is intentionally conservative and pattern based rather than a model call so it runs
inline during capture with no dependency on the network.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RedactionRule:
    """A named regular expression and the placeholder it is replaced with."""

    name: str
    pattern: re.Pattern[str]
    placeholder: str


def _rule(name: str, pattern: str, placeholder: str) -> RedactionRule:
    return RedactionRule(name=name, pattern=re.compile(pattern), placeholder=placeholder)


# Order matters: more specific patterns first so they win over generic ones.
DEFAULT_RULES: tuple[RedactionRule, ...] = (
    _rule(
        "api_key",
        # Common provider token shapes (sk-..., xoxb-..., ghp_..., AKIA...).
        r"\b(?:sk-[A-Za-z0-9]{16,}|xox[baprs]-[A-Za-z0-9-]{8,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b",
        "[REDACTED_SECRET]",
    ),
    _rule(
        "email",
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "[REDACTED_EMAIL]",
    ),
    _rule(
        "credit_card",
        r"\b(?:\d[ -]*?){13,16}\b",
        "[REDACTED_CARD]",
    ),
    _rule(
        "phone",
        r"\b(?:\+?\d{1,3}[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]?\d{4}\b",
        "[REDACTED_PHONE]",
    ),
)


class Redactor:
    """Applies redaction rules to strings and nested structures.

    Parameters
    ----------
    rules:
        The rule set to apply. Defaults to :data:`DEFAULT_RULES`.
    redact_keys:
        Object keys whose values are always fully redacted regardless of content,
        such as ``password`` or ``authorization``.
    """

    def __init__(
        self,
        rules: Iterable[RedactionRule] | None = None,
        redact_keys: Iterable[str] | None = None,
    ) -> None:
        self.rules = tuple(rules) if rules is not None else DEFAULT_RULES
        self.redact_keys = {k.lower() for k in (redact_keys or ["password", "secret", "authorization", "token"])}

    def redact_text(self, text: str) -> tuple[str, set[str]]:
        """Redact a string. Returns the cleaned text and the set of rule names hit."""
        hits: set[str] = set()
        out = text
        for rule in self.rules:
            if rule.pattern.search(out):
                hits.add(rule.name)
                out = rule.pattern.sub(rule.placeholder, out)
        return out, hits

    def redact(self, value: Any) -> tuple[Any, set[str]]:
        """Recursively redact a JSON like value.

        Returns the redacted copy and the union of rule names triggered anywhere in
        the structure, which the caller records on the span's ``redactions`` list.
        """
        hits: set[str] = set()

        def walk(node: Any, key: str | None = None) -> Any:
            if key is not None and key.lower() in self.redact_keys:
                hits.add(f"key:{key.lower()}")
                return "[REDACTED]"
            if isinstance(node, str):
                cleaned, found = self.redact_text(node)
                hits.update(found)
                return cleaned
            if isinstance(node, dict):
                return {k: walk(v, k) for k, v in node.items()}
            if isinstance(node, (list, tuple)):
                return [walk(v) for v in node]
            # Numeric scalars can carry sensitive values too (a card or phone number
            # stored as an int), so scan their string form. Booleans are excluded
            # because bool is an int subclass and never sensitive.
            if isinstance(node, (int, float)) and not isinstance(node, bool):
                cleaned, found = self.redact_text(str(node))
                if found:
                    hits.update(found)
                    return cleaned
            return node

        redacted = walk(value)
        return redacted, hits
