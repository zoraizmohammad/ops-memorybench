"""Anthropic Claude client behind the LLM interface.

The live path. Translates the platform's provider neutral :class:`Message` and
:class:`ToolSpec` types into Anthropic Messages API calls and back. The Anthropic SDK
is imported lazily inside the constructor so that importing this module never breaks
the keyless path where the dependency is absent.

Defaults follow current Anthropic guidance: model ``claude-opus-4-8``, adaptive
thinking, and no sampling parameters (which the Opus 4.8 surface rejects). Tool use
follows the documented loop shape: assistant turns may contain ``tool_use`` blocks,
and tool results are returned as ``tool_result`` content blocks keyed by
``tool_use_id``.
"""

from __future__ import annotations

from typing import Any

from .base import (
    LLMClient,
    LLMResponse,
    Message,
    Role,
    StopReason,
    ToolCall,
    ToolSpec,
)

# Published Anthropic pricing per token (USD) for the default model, used for cost
# accounting in the eval harness. claude-opus-4-8 is $5 / $25 per million tokens.
_PRICING = {
    "claude-opus-4-8": (5.0 / 1_000_000, 25.0 / 1_000_000),
    "claude-sonnet-4-6": (3.0 / 1_000_000, 15.0 / 1_000_000),
    "claude-haiku-4-5": (1.0 / 1_000_000, 5.0 / 1_000_000),
}


class AnthropicLLM(LLMClient):
    """Live Claude client implementing the platform LLM interface."""

    def __init__(self, *, api_key: str, model: str = "claude-opus-4-8") -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise RuntimeError(
                "The anthropic package is required for the live LLM path. "
                "Install it with pip install 'ombench[llm]'."
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.price_in, self.price_out = _PRICING.get(model, (0.0, 0.0))

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        api_messages = [self._to_api_message(m) for m in messages]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": api_messages,
            # Adaptive thinking is the recommended setting on Opus 4.8 and lets the
            # model decide how much to think. No budget_tokens, no sampling params.
            "thinking": {"type": "adaptive"},
        }
        if tools:
            kwargs["tools"] = [self._to_api_tool(t) for t in tools]

        response = self._client.messages.create(**kwargs)
        return self._from_api_response(response)

    # -- translation ------------------------------------------------------

    def _to_api_tool(self, tool: ToolSpec) -> dict[str, Any]:
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }

    def _to_api_message(self, message: Message) -> dict[str, Any]:
        if message.tool_results:
            content = [
                {
                    "type": "tool_result",
                    "tool_use_id": tr["tool_call_id"],
                    "content": tr.get("content", ""),
                }
                for tr in message.tool_results
            ]
            return {"role": "user", "content": content}
        if message.tool_calls:
            content: list[dict[str, Any]] = []
            if message.content:
                content.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                content.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.arguments,
                    }
                )
            return {"role": "assistant", "content": content}
        role = "assistant" if message.role == Role.ASSISTANT else "user"
        return {"role": role, "content": message.content}

    def _from_api_response(self, response: Any) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )
        stop = response.stop_reason
        stop_reason = {
            "tool_use": StopReason.TOOL_USE,
            "max_tokens": StopReason.MAX_TOKENS,
        }.get(stop, StopReason.END_TURN)
        usage = response.usage
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            input_tokens=getattr(usage, "input_tokens", 0),
            output_tokens=getattr(usage, "output_tokens", 0),
            model=self.model,
        )
