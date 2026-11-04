"""
test_agent_core_loop_v2 — LOOP_V2 接线层单测（P1-1）。

不构造完整 AgentCore（__init__ 会拉起 DB/向量库/工具），
用 __new__ + 显式依赖注入，只验证接线逻辑：
- 老路径开关默认关闭；
- LoopResult.reason → 现有话术映射；
- runner 调用参数（budget / tools / 首步强制工具 / user_id）；
- ToolOutcome 的副作用标记能被旧 _process_tool_side_effects 消费。
"""
import sys

sys.path.insert(0, ".")

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from packages.agent.agent_core import (
    AgentCore,
    DEGRADED_REPLY,
    _env_flag,
    _looks_like_multi_intent,
)
from packages.agent.loop import LoopBudget, LoopResult, ToolOutcome
from packages.shared.events import InternalEvent


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_weather",
            "description": "查天气",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
        },
    }
]


def _event(payload: str = "杭州天气", user_id: str = "hezi") -> InternalEvent:
    return InternalEvent(source="test", user_id=user_id, payload=payload, is_owner=True)


def _bare_agent(loop_result: LoopResult | None = None):
    """空 AgentCore，只注入接线需要的属性。"""
    agent = AgentCore.__new__(AgentCore)
    agent.router = MagicMock()
    agent.tool_executor = MagicMock()
    agent._loop_v2 = True
    agent._loop_budget = LoopBudget(max_steps=3, max_tokens=1234)
    agent._loop_runner = StubLoopRunner(loop_result or LoopResult())
    agent._clean_reply = MagicMock(side_effect=lambda text: (text or "").strip())
    agent._process_tool_side_effects = MagicMock()
    return agent


class StubLoopRunner:
    """记录调用参数，返回预置 LoopResult。"""

    def __init__(self, result: LoopResult):
        self.result = result
        self.calls: list[dict] = []

    async def run_to_result(self, messages, tools=None, budget=None, **kwargs):
        self.calls.append(
            {"messages": messages, "tools": tools, "budget": budget, **kwargs}
        )
        return self.result


# ─────────────────────────────────────────────────────────────
# 开关默认值
# ─────────────────────────────────────────────────────────────


def test_loop_v2_env_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("LOOP_V2", raising=False)
    assert _env_flag("LOOP_V2", False) is False

    monkeypatch.setenv("LOOP_V2", "1")
    assert _env_flag("LOOP_V2", False) is True

    monkeypatch.setenv("LOOP_V2", "off")
    assert _env_flag("LOOP_V2", False) is False


# ─────────────────────────────────────────────────────────────
# reason → 话术映射
# ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (LoopResult(text="  杭州 18℃。  ", reason="stop"), "杭州 18℃。"),
        (LoopResult(text="", reason="empty"), ""),
        (LoopResult(text="", reason="error"), DEGRADED_REPLY),
        (LoopResult(text="人家查得有点久了……", reason="budget_time"), "人家查得有点久了……"),
        (LoopResult(text="预算到了", reason="budget_tokens"), "预算到了"),
        (LoopResult(text="步骤到了", reason="max_steps"), "步骤到了"),
    ],
)
def test_loop_reply_mapping(result, expected):
    agent = _bare_agent()
    assert agent._loop_reply(result) == expected


def test_loop_reply_confirmation_is_explicit():
    agent = _bare_agent()
    reply = agent._loop_reply(LoopResult(reason="confirmation"))
    assert "确认" in reply


# ─────────────────────────────────────────────────────────────
# runner 调用参数
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_loop_v2_passes_budget_tools_and_forced_tool():
    result = LoopResult(
        text="杭州 18℃。",
        reason="stop",
        steps=2,
        tool_calls=1,
        usage={"total_tokens": 30},
        tool_outcomes=[
            ToolOutcome(call_id="c1", name="query_weather", ok=True, data={"temp": 18})
        ],
    )
    agent = _bare_agent(result)
    trace_log = MagicMock()

    got = await agent._run_loop_v2(
        messages=[{"role": "user", "content": "杭州天气"}],
        tools=TOOLS,
        forced_tool="query_weather",
        emo_params={"temperature": 0.5, "max_tokens": 200},
        event=_event(user_id="partner"),
        trace_log=trace_log,
    )

    assert got is result
    call = agent._loop_runner.calls[0]
    assert call["tools"] == TOOLS
    assert call["budget"] is agent._loop_budget
    assert call["temperature"] == 0.5
    assert call["max_tokens"] == 200
    assert call["user_id"] == "partner"
    assert call["first_tool_choice"] == {
        "type": "function",
        "function": {"name": "query_weather"},
    }
    trace_log.info.assert_called_once()


@pytest.mark.asyncio
async def test_run_loop_v2_auto_when_intent_not_forced():
    agent = _bare_agent(LoopResult(text="好", reason="stop"))

    await agent._run_loop_v2(
        messages=[],
        tools=TOOLS,
        forced_tool=None,
        emo_params={"temperature": 0.7, "max_tokens": 800},
        event=_event(),
        trace_log=MagicMock(),
    )

    assert agent._loop_runner.calls[0]["first_tool_choice"] == "auto"


def test_multi_intent_detector():
    assert _looks_like_multi_intent("查下杭州天气，顺便搜一下北京好玩的地方")
    assert _looks_like_multi_intent("先看看北京天气，再帮我搜下有什么好玩的")
    assert _looks_like_multi_intent("帮我查杭州天气，再回忆一下上次说的旅行")

    assert not _looks_like_multi_intent("杭州今天天气怎么样")
    assert not _looks_like_multi_intent("今天好累啊，再陪我聊聊")


@pytest.mark.asyncio
async def test_run_loop_v2_injects_multi_intent_hint():
    agent = _bare_agent(LoopResult(text="好", reason="stop"))
    messages = [{"role": "user", "content": "查下杭州天气，顺便搜一下北京好玩的地方"}]

    await agent._run_loop_v2(
        messages=messages,
        tools=TOOLS,
        forced_tool=None,
        emo_params={"temperature": 0.7, "max_tokens": 800},
        event=_event(payload="查下杭州天气，顺便搜一下北京好玩的地方"),
        trace_log=MagicMock(),
    )

    sent = agent._loop_runner.calls[0]["messages"]
    assert len(sent) == 2
    assert sent[0]["role"] == "system"
    assert "工具规划" in sent[0]["content"]
    assert sent[-1]["role"] == "user"
    # 不改调用方原列表
    assert messages == [{"role": "user", "content": "查下杭州天气，顺便搜一下北京好玩的地方"}]


@pytest.mark.asyncio
async def test_run_loop_v2_single_intent_has_no_hint():
    agent = _bare_agent(LoopResult(text="好", reason="stop"))
    messages = [{"role": "user", "content": "杭州天气怎么样"}]

    await agent._run_loop_v2(
        messages=messages,
        tools=TOOLS,
        forced_tool=None,
        emo_params={"temperature": 0.7, "max_tokens": 800},
        event=_event(payload="杭州天气怎么样"),
        trace_log=MagicMock(),
    )

    assert agent._loop_runner.calls[0]["messages"] == messages


@pytest.mark.asyncio
async def test_run_loop_v2_forwards_event_sink():
    agent = _bare_agent(LoopResult(text="好", reason="stop"))
    sink = AsyncMock()

    await agent._run_loop_v2(
        messages=[],
        tools=TOOLS,
        forced_tool=None,
        emo_params={"temperature": 0.7, "max_tokens": 800},
        event=_event(),
        trace_log=MagicMock(),
        event_sink=sink,
    )

    assert agent._loop_runner.calls[0]["on_event"] is sink
    assert agent._loop_runner.calls[0]["stream"] is False


@pytest.mark.asyncio
async def test_run_loop_v2_forwards_stream_flag():
    agent = _bare_agent(LoopResult(text="好", reason="stop"))
    sink = AsyncMock()

    await agent._run_loop_v2(
        messages=[],
        tools=TOOLS,
        forced_tool=None,
        emo_params={"temperature": 0.7, "max_tokens": 800},
        event=_event(),
        trace_log=MagicMock(),
        event_sink=sink,
        stream=True,
    )

    assert agent._loop_runner.calls[0]["stream"] is True


# ─────────────────────────────────────────────────────────────
# 副作用标记复用
# ─────────────────────────────────────────────────────────────


def test_tool_outcome_flags_feed_existing_side_effects():
    agent = _bare_agent()
    agent._schedule_memory_encoding = MagicMock()
    agent.portrait_manager = MagicMock()
    outcome = ToolOutcome(
        call_id="c1",
        name="search_memory",
        ok=True,
        trigger_memory=True,
        trigger_portrait_update=True,
    )

    AgentCore._process_tool_side_effects(
        agent, [("search_memory", outcome)], "伙伴的消息"
    )

    agent._schedule_memory_encoding.assert_called_once()
    agent.portrait_manager.mark_dirty.assert_called_once()


def test_tool_outcome_without_flags_has_no_side_effect():
    agent = _bare_agent()
    agent._schedule_memory_encoding = MagicMock()
    agent.portrait_manager = MagicMock()
    outcome = ToolOutcome(call_id="c1", name="query_weather", ok=True)

    AgentCore._process_tool_side_effects(agent, [("query_weather", outcome)], "")

    agent._schedule_memory_encoding.assert_not_called()
    agent.portrait_manager.mark_dirty.assert_not_called()
