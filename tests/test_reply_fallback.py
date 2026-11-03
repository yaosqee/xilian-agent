"""空回复 / 语音兜底 / 截断重试 的单元测试（2026-11-03 修复）。

覆盖：
- `_clean_reply("")` 不再伪造「……♪」
- `_build_speech_fallback()` 引用「这一轮」的用户消息，而不是 history 里的旧消息
- `ModelRouter._retry_if_empty()`：空 content / finish_reason=length 时提高预算重试一次
"""
import sys

sys.path.insert(0, ".")

import pytest
from types import SimpleNamespace

from packages.agent.agent_core import AgentCore
from packages.shared.model_router import ModelRouter
from packages.shared.providers import ProviderResponse


# ── 语音兜底 ──────────────────────────────────────────────

def _bare_agent(history=None, current_msg=""):
    agent = AgentCore.__new__(AgentCore)
    agent.context = SimpleNamespace(history=history or [])
    agent._current_user_msg = current_msg
    return agent


def test_clean_reply_empty_returns_empty_string():
    """空内容返回空串，交给上层显式降级，而不是伪装成「……♪」。"""
    agent = _bare_agent()
    assert agent._clean_reply("") == ""
    assert agent._clean_reply("   \n ") == ""


def test_speech_fallback_uses_current_message_not_history():
    history = [{"role": "user", "content": "（150天前）那晚安。每天见"},
               {"role": "assistant", "content": "晚安"}]
    agent = _bare_agent(history=history, current_msg="你好，你叫什么名字？")

    out = agent._enforce_speech_rule("……♪")

    assert "你叫什么名字" in out
    assert "150天前" not in out


def test_speech_fallback_falls_back_to_history_when_no_current():
    agent = _bare_agent(history=[{"role": "user", "content": "今天好累啊"}])
    out = agent._enforce_speech_rule("（轻轻合上书）")
    assert "今天好累啊" in out


# ── 截断 / 空回复重试 ────────────────────────────────────

class _FakeAdapter:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


MESSAGES = [{"role": "user", "content": "你好"}]


@pytest.mark.asyncio
async def test_retry_on_empty_content():
    empty = ProviderResponse(content="", model="m", finish_reason="stop")
    good = ProviderResponse(content="人家是昔涟。", model="m", finish_reason="stop")
    adapter = _FakeAdapter([good])
    router = ModelRouter.__new__(ModelRouter)

    out = await router._retry_if_empty(
        empty, adapter, "m", MESSAGES, None, None,
        {"max_tokens": 800, "temperature": 0.6},
    )

    assert out is good
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["max_tokens"] == 1600  # 800*2
    assert adapter.calls[0]["stream"] is False


@pytest.mark.asyncio
async def test_retry_on_truncated_even_with_partial_content():
    truncated = ProviderResponse(content="人家", model="m", finish_reason="length")
    good = ProviderResponse(content="人家是昔涟。", model="m", finish_reason="stop")
    adapter = _FakeAdapter([good])
    router = ModelRouter.__new__(ModelRouter)

    out = await router._retry_if_empty(
        truncated, adapter, "m", MESSAGES, None, None,
        {"max_tokens": 1500, "temperature": 0.6},
    )

    assert out is good
    assert adapter.calls[0]["max_tokens"] == 3000  # 1500*2


@pytest.mark.asyncio
async def test_no_retry_on_healthy_response():
    good = ProviderResponse(content="人家在呢。", model="m", finish_reason="stop")
    adapter = _FakeAdapter([])
    router = ModelRouter.__new__(ModelRouter)

    out = await router._retry_if_empty(
        good, adapter, "m", MESSAGES, None, None,
        {"max_tokens": 800, "temperature": 0.6},
    )

    assert out is good
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_retry_still_empty_returns_retry_result():
    empty = ProviderResponse(content="", model="m", finish_reason="length")
    still_empty = ProviderResponse(content="", model="m", finish_reason="length")
    adapter = _FakeAdapter([still_empty])
    router = ModelRouter.__new__(ModelRouter)

    out = await router._retry_if_empty(
        empty, adapter, "m", MESSAGES, None, None,
        {"max_tokens": 800, "temperature": 0.6},
    )

    assert out is still_empty
    assert len(adapter.calls) == 1


@pytest.mark.asyncio
async def test_tool_only_response_is_not_retried():
    tool_only = ProviderResponse(
        content=None, model="m", finish_reason="tool_calls",
        tool_calls=[{"id": "c1", "function": {"name": "query_weather", "arguments": "{}"}}],
    )
    adapter = _FakeAdapter([])
    router = ModelRouter.__new__(ModelRouter)

    out = await router._retry_if_empty(
        tool_only, adapter, "m", MESSAGES, None, None,
        {"max_tokens": 800, "temperature": 0.6},
    )

    assert out is tool_only
    assert adapter.calls == []
