"""意图路由层 + 工具溯源回归测试（工具系统第三批）。"""
import sys

sys.path.insert(0, ".")

import pytest

from packages.agent.agent_core import AgentCore
from packages.agent.agent_context import AgentContext


@pytest.fixture
def agent():
    # 仅测试纯方法（_route_intent / _looks_like_factual / _mark_unverified），
    # 用 __new__ 跳过 __init__ 的重初始化（DB/路由/上下文构建）。
    return AgentCore.__new__(AgentCore)


# ── 3.1 意图路由 ──────────────────────────────────────────

def test_route_intent_weather_with_city(agent):
    assert agent._route_intent("杭州天气怎么样") == "query_weather"
    assert agent._route_intent("今天北京多少度") == "query_weather"


def test_route_intent_weather_time_generic(agent):
    assert agent._route_intent("今天天气怎么样") == "query_weather"
    assert agent._route_intent("明天会下雨吗") == "query_weather"


def test_route_intent_search(agent):
    assert agent._route_intent("帮我查一下 python asyncio 用法") == "search_web"
    assert agent._route_intent("搜一下最近的新闻") == "search_web"


def test_route_intent_memory(agent):
    assert agent._route_intent("你还记得我之前说过什么吗") == "search_memory"
    assert agent._route_intent("上次我们聊到哪里了") == "search_memory"


def test_route_intent_none(agent):
    # 普通闲聊不强制路由，交给 LLM auto
    assert agent._route_intent("今天好累啊") is None
    assert agent._route_intent("讲个笑话吧") is None


# ── 3.2 工具溯源（推测标记）───────────────────────────────

def test_looks_like_factual(agent):
    assert agent._looks_like_factual("今天杭州气温25度") is True
    assert agent._looks_like_factual("今天杭州25度呢") is True  # 单点温度（正则漏判，此处应命中）
    assert agent._looks_like_factual("今天心情不错") is False


def test_mark_unverified_flags_factual_without_tool(agent):
    reply = "今天杭州25度呢"
    out = agent._mark_unverified(reply, forced_tool=None, tools_called=False)
    assert out.startswith("[注意：以下为昔涟的推测")


def test_mark_unverified_skips_when_tool_called(agent):
    reply = "今天杭州25度呢"
    out = agent._mark_unverified(reply, forced_tool=None, tools_called=True)
    assert out == reply


def test_mark_unverified_skips_when_forced_tool(agent):
    reply = "今天杭州25度呢"
    out = agent._mark_unverified(reply, forced_tool="query_weather", tools_called=False)
    assert out == reply


def test_mark_unverified_skips_non_factual(agent):
    reply = "今天心情不错呢"
    out = agent._mark_unverified(reply, forced_tool=None, tools_called=False)
    assert out == reply


# ── 工具溯源：add_message source 字段 ─────────────────────

def test_add_message_source_field():
    ctx = AgentContext()
    ctx.add_message("assistant", "今天杭州晴朗", source="tool_query_weather")
    assert ctx.history[-1]["source"] == "tool_query_weather"
    assert "content" in ctx.history[-1]


def test_add_message_no_source_default():
    ctx = AgentContext()
    ctx.add_message("user", "你好")
    assert "source" not in ctx.history[-1]
