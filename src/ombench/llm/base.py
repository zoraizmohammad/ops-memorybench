"""LLM client interface.

The platform's agent under test and LLM judge both talk to an LLM through this one
interface, so the provider is pluggable. Two implementations ship: a deterministic
stub (no key, fully reproducible) and an Anthropic Claude client (live). The
interface is a small message and tool-use surface modeled on the Anthropic Messages
API, which is the shape the agent loop expects.

A response carries either text, tool-use requests, or both, plus a stop reason and
token usage, so the agent can run a tool loop and the eval harness can account for
cost.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class StopReason(StrEnum):
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"


@dataclass
class ToolSpec:
    """A tool the model may call, in the name and JSON schema shape the API expects."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    """A model request to call a tool."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    """One conversation message.

    ``tool_calls`` is populated on assistant turns that request tools.
    ``tool_results`` is populated on user turns that return tool outputs, each a
    mapping with ``tool_call_id`` and ``content``.
    """

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class LLMResponse:
    """A model response."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: StopReason = StopReason.END_TURN
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    @property
    def wants_tool(self) -> bool:
        return self.stop_reason == StopReason.TOOL_USE and bool(self.tool_calls)


class LLMClient(ABC):
    """Provider neutral chat interface."""

    model: str

    @abstractmethod
    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Produce one assistant response given the conversation so far."""
        raise NotImplementedError

    # -- cost accounting --------------------------------------------------

    #: Price per input/output token in USD, overridden per provider and model.
    price_in: float = 0.0
    price_out: float = 0.0

    def cost_usd(self, response: LLMResponse) -> float:
        return response.input_tokens * self.price_in + response.output_tokens * self.price_out
