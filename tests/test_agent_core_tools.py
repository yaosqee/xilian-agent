"""AgentCore 核心工具回路单元测试（第四批：测试补强）。

覆盖：_handle_tool_calls（工具迭代 + 空结果）/ _handle_confirmation（确认回路）/
_sanitize_fabrication（编造清洗）。_schedule_compression 见 test_agent_context.py。
"""
import sys

sys.path.insert(0, ".")

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from loguru import logger

from packages.agent.agent_core import AgentCore
from packages.agent.tool_result import ToolResult
from packages.shared.events import InternalEvent


def _bare_agent():
    """用 __new__ 构造空 AgentCore，手动注入所需依赖，避免 __init__ 的重初始化。"""
    agent = AgentCore.__new__(AgentCore)
    agent._emotion_modulated_params = MagicMock(
        return_value={"temperature": 0.7, "max_tokens": 500}
    )
    agent._clean_reply = MagicMock(side_effect=lambda x: (x or "").strip())
    return agent


def _event(payload: str) -> InternalEvent:
    return InternalEvent(source="test", user_id="hezi", payload=payload, is_owner=True)


# ── _handle_tool_calls ────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_tool_calls_executes_and_returns():
    agent = _bare_agent()
    agent.tool_executor = MagicMock()
    agent.tool_executor.execute = AsyncMock(return_value=ToolResult.ok({"results": ["记忆A"]}))
    agent.result_wrapper = MagicMock()
    agent.result_wrapper.wrap = AsyncMock(return_value="（查到一些记忆）")
    agent.router = MagicMock()
    agent.router.route = AsyncMock(return_value=SimpleNamespace(content="人家想起来了~", tool_calls=None))

    message = SimpleNamespace(
        content="",
        tool_calls=[{"id": "c1", "function": {"name": "search_memory", "arguments": '{"query": "test"}'}}],
    )

    reply, tool_results = await agent._handle_tool_calls(
        message, _event("测试"), [{"role": "user", "content": "测试"}], MagicMock(),
    )

    assert reply == "人家想起来了~"
    assert [tn for tn, _ in tool_results] == ["search_memory"]
    agent.tool_executor.execute.assert_awaited_once()
    agent.result_wrapper.wrap.assert_awaited_once()
    agent.router.route.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_tool_calls_empty_result_injects_no_fabricate_hint():
    agent = _bare_agent()
    agent.tool_executor = MagicMock()
    agent.tool_executor.execute = AsyncMock(return_value=ToolResult.fail("没查到"))
    agent.result_wrapper = MagicMock()
    agent.result_wrapper.wrap = AsyncMock()
    agent.router = MagicMock()
    agent.router.route = AsyncMock(return_value=SimpleNamespace(content="人家没查到呢", tool_calls=None))

    message = SimpleNamespace(
        content="",
        tool_calls=[{"id": "c1", "function": {"name": "query_weather", "arguments": '{"city": "杭州"}'}}],
    )

    reply, tool_results = await agent._handle_tool_calls(
        message, _event("杭州天气"), [{"role": "user", "content": "杭州天气"}], MagicMock(),
    )

    assert reply == "人家没查到呢"
    # 失败结果不走 wrap，而是注入「不要编造」提示
    agent.result_wrapper.wrap.assert_not_awaited()
    follow_up = agent.router.route.call_args.args[1]
    tool_msg = next(m for m in follow_up if m.get("role") == "tool")
    assert "不要编造" in tool_msg["content"]


# ── _handle_confirmation ──────────────────────────────────

@pytest.mark.asyncio
async def test_handle_confirmation_executes_tool():
    agent = _bare_agent()
    agent._pending_confirmation = {"tool_name": "coding_delegate", "arguments": {"task": "test"}}
    agent.tool_executor = MagicMock()
    agent.tool_executor.execute = AsyncMock(return_value=ToolResult.ok({"done": True}))
    agent.result_wrapper = MagicMock()
    agent.result_wrapper.wrap = AsyncMock(return_value="执行好啦~")

    reply, tool_results = await agent._handle_confirmation(_event("确认"), MagicMock())

    assert reply == "执行好啦~"
    assert [tn for tn, _ in tool_results] == ["coding_delegate"]
    agent.tool_executor.execute.assert_awaited_once_with(
        "coding_delegate", {"task": "test"}, user_id="hezi"
    )


@pytest.mark.asyncio
async def test_handle_confirmation_cancels_on_other_text():
    agent = _bare_agent()
    agent._pending_confirmation = {"tool_name": "coding_delegate", "arguments": {}}

    result = await agent._handle_confirmation(_event("算了不用了"), MagicMock())

    assert result is None
    assert agent._pending_confirmation is None


# ── _sanitize_fabrication ─────────────────────────────────

def test_sanitize_fabrication_skips_when_tool_called():
    agent = _bare_agent()
    assert agent._sanitize_fabrication("今天杭州25度", tools_called=True) == "今天杭州25度"


def test_sanitize_fabrication_replaces_weather_data():
    agent = _bare_agent()
    out = agent._sanitize_fabrication("今天杭州气温25度呢", tools_called=False)
    assert "（未查询）" in out
    assert "25" not in out


def test_sanitize_fabrication_leaves_normal_reply():
    agent = _bare_agent()
    assert agent._sanitize_fabrication("今天心情不错", tools_called=False) == "今天心情不错"
