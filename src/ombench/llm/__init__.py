"""ombench.llm subpackage.

A pluggable LLM layer. The agent under test and the LLM judge talk to an
:class:`LLMClient`; :func:`build_llm` selects the implementation from config, falling
back to the deterministic stub whenever a live provider is requested without a key so
the platform always runs.
"""

from __future__ import annotations

from ..config import Config, load_config
from .base import (
    LLMClient,
    LLMResponse,
    Message,
    Role,
    StopReason,
    ToolCall,
    ToolSpec,
)
from .stub import StubLLM

__all__ = [
    "LLMClient",
    "LLMResponse",
    "Message",
    "Role",
    "StopReason",
    "StubLLM",
    "ToolCall",
    "ToolSpec",
    "build_llm",
]


def build_llm(config: Config | None = None, *, model: str | None = None) -> LLMClient:
    """Build the configured LLM client.

    Returns the Anthropic client when the provider resolves to anthropic and a key is
    present, otherwise the deterministic stub. The effective provider already accounts
    for a missing key, so this never raises for lack of credentials.
    """
    config = config or load_config()
    if config.llm.effective_provider == "anthropic":
        from .anthropic_client import AnthropicLLM

        return AnthropicLLM(
            api_key=config.llm.anthropic_api_key,
            model=model or config.llm.model,
        )
    return StubLLM()
