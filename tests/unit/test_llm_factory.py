"""Tests for LLM client selection and the Anthropic translation layer.

The Anthropic client is exercised with a fake SDK client so the translation logic is
covered without a network call or an API key.
"""

from __future__ import annotations

from types import SimpleNamespace

from ombench.config import Config, LLMConfig
from ombench.llm import build_llm
from ombench.llm.anthropic_client import AnthropicLLM
from ombench.llm.base import Message, Role, StopReason, ToolCall, ToolSpec
from ombench.llm.stub import StubLLM


def test_build_llm_defaults_to_stub():
    cfg = Config(llm=LLMConfig(provider="stub"))
    assert isinstance(build_llm(cfg), StubLLM)


def test_build_llm_falls_back_to_stub_without_key():
    cfg = Config(llm=LLMConfig(provider="anthropic", anthropic_api_key=""))
    assert isinstance(build_llm(cfg), StubLLM)


def _fake_response(*, text="", tool_uses=None, stop="end_turn"):
    content = []
    if text:
        content.append(SimpleNamespace(type="text", text=text))
    for tu in tool_uses or []:
        content.append(SimpleNamespace(type="tool_use", id=tu["id"], name=tu["name"], input=tu["input"]))
    return SimpleNamespace(
        content=content,
        stop_reason=stop,
        usage=SimpleNamespace(input_tokens=100, output_tokens=20),
    )


def _make_client(monkeypatch, captured, response):
    """Build an AnthropicLLM whose SDK client is faked."""
    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.model = "claude-opus-4-8"
    llm.price_in, llm.price_out = 5.0 / 1_000_000, 25.0 / 1_000_000

    def create(**kwargs):
        captured.update(kwargs)
        return response

    llm._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return llm


def test_anthropic_translation_text_response(monkeypatch):
    captured: dict = {}
    llm = _make_client(monkeypatch, captured, _fake_response(text="hello"))
    resp = llm.complete(system="sys", messages=[Message(role=Role.USER, content="hi")])
    assert resp.text == "hello"
    assert resp.stop_reason == StopReason.END_TURN
    assert resp.input_tokens == 100
    # Adaptive thinking is requested and no sampling params are sent.
    assert captured["thinking"] == {"type": "adaptive"}
    assert "temperature" not in captured


def test_anthropic_translation_tool_use(monkeypatch):
    captured: dict = {}
    response = _fake_response(
        tool_uses=[{"id": "tu1", "name": "slack.post", "input": {"channel": "C1"}}],
        stop="tool_use",
    )
    llm = _make_client(monkeypatch, captured, response)
    tools = [ToolSpec(name="slack.post", description="post", input_schema={"type": "object"})]
    resp = llm.complete(system="sys", messages=[Message(role=Role.USER, content="post")], tools=tools)
    assert resp.wants_tool
    assert resp.tool_calls[0].name == "slack.post"
    assert resp.tool_calls[0].arguments == {"channel": "C1"}
    # Tools were translated into the API shape.
    assert captured["tools"][0]["name"] == "slack.post"


def test_anthropic_tool_result_message_translation(monkeypatch):
    captured: dict = {}
    llm = _make_client(monkeypatch, captured, _fake_response(text="done"))
    messages = [
        Message(role=Role.USER, content="post"),
        Message(role=Role.ASSISTANT, tool_calls=[ToolCall(id="tu1", name="slack.post", arguments={})]),
        Message(role=Role.USER, tool_results=[{"tool_call_id": "tu1", "content": "{\"ok\": true}"}]),
    ]
    llm.complete(system="sys", messages=messages)
    api_messages = captured["messages"]
    # The tool result message became a tool_result content block keyed by id.
    assert api_messages[-1]["content"][0]["type"] == "tool_result"
    assert api_messages[-1]["content"][0]["tool_use_id"] == "tu1"
    # The assistant tool call became a tool_use content block.
    assert api_messages[1]["content"][0]["type"] == "tool_use"


def test_cost_accounting(monkeypatch):
    captured: dict = {}
    llm = _make_client(monkeypatch, captured, _fake_response(text="x"))
    resp = llm.complete(system="sys", messages=[Message(role=Role.USER, content="hi")])
    cost = llm.cost_usd(resp)
    assert cost == 100 * (5.0 / 1_000_000) + 20 * (25.0 / 1_000_000)
