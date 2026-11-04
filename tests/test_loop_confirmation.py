"""
test_loop_confirmation — P2 会话级确认状态机（内存版）。

覆盖：
- ConfirmationStore 按 (user_id, session_id) 隔离 + TTL；
- runner 遇 PENDING_CONFIRMATION 时保留 pending / 可恢复消息；
- AgentCore 确认后执行 pending 并继续循环；
- 非确认文本取消、其它会话不串。
"""
import sys

sys.path.insert(0, ".")

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from packages.agent.agent_context import AgentContext
from packages.agent.agent_core import AgentCore
from packages.agent.loop import (
    AgentLoopRunner,
    ConfirmationStore,
    LoopBudget,
    LoopResult,
    LoopToolExecutor,
    ToolCall,
    ToolOutcome,
)
from packages.agent.tool_result import ToolResult
from packages.shared.events import InternalEvent


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "coding_delegate",
            "description": "执行代码任务",
            "parameters": {"type": "object", "properties": {"task": {"type": "string"}}},
        },
    }
]


def _call(call_id: str = "c1", task: str = "rm") -> ToolCall:
    return ToolCall(
        id=call_id,
        name="coding_delegate",
        arguments={"task": task},
        raw_arguments='{"task": "%s"}' % task,
    )


def _event(payload: str, *, user_id: str = "hezi", session_id: str = "web") -> InternalEvent:
    return InternalEvent(
        source="http",
        user_id=user_id,
        session_id=session_id,
        payload=payload,
        is_owner=True,
    )


# ─────────────────────────────────────────────────────────────
# ConfirmationStore
# ─────────────────────────────────────────────────────────────


def test_store_isolates_sessions():
    store = ConfirmationStore(ttl_seconds=60, clock=lambda: 0.0)
    store.put("hezi", "web", [_call("c1")], [{"role": "assistant", "content": ""}])
    store.put("hezi", "console", [_call("c2")], [])

    assert store.get("hezi", "web").calls[0].id == "c1"
    assert store.get("hezi", "console").calls[0].id == "c2"
    assert store.get("other", "web") is None

    store.discard("hezi", "web")
    assert store.get("hezi", "web") is None
    assert store.get("hezi", "console") is not None


def test_store_expires_pending():
    now = [0.0]
    store = ConfirmationStore(ttl_seconds=10, clock=lambda: now[0])
    store.put("hezi", "web", [_call()], [])

    now[0] = 9.9
    assert store.get("hezi", "web") is not None

    now[0] = 10.0
    assert store.get("hezi", "web") is None
    assert len(store) == 0


def test_store_same_session_overwrites():
    store = ConfirmationStore(ttl_seconds=60, clock=lambda: 0.0)
    store.put("hezi", "web", [_call("old")], [])
    store.put("hezi", "web", [_call("new")], [])

    assert [call.id for call in store.get("hezi", "web").calls] == ["new"]


# ─────────────────────────────────────────────────────────────
# Runner：确认暂停保留上下文
# ─────────────────────────────────────────────────────────────


class OneShotRouter:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def route(self, task_type, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return self.response


class ConfirmingExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, name, arguments, user_id=""):
        self.calls.append((name, arguments, user_id))
        return ToolResult(
            success=False,
            error="PENDING_CONFIRMATION",
            data={"tool_name": name, "arguments": arguments},
        )


@pytest.mark.asyncio
async def test_runner_pauses_with_pending_and_resume_messages():
    response = SimpleNamespace(
        content="",
        tool_calls=[{
            "id": "c1",
            "type": "function",
            "function": {
                "name": "coding_delegate",
                "arguments": '{"task": "rm"}',
            },
        }],
        usage={"total_tokens": 10},
        reasoning_content=None,
    )
    runner = AgentLoopRunner(
        OneShotRouter(response),
        LoopToolExecutor(ConfirmingExecutor()),
        user_id="hezi",
    )

    result = await runner.run_to_result(
        [{"role": "user", "content": "帮我删个东西"}],
        TOOLS,
        LoopBudget(max_steps=3),
    )

    assert result.reason == "confirmation"
    assert [call.id for call in result.pending] == ["c1"]
    assert result.pending[0].name == "coding_delegate"
    assert result.tool_outcomes[0].needs_confirmation is True

    # 可恢复上下文：assistant(tool_calls) 已入，pending 的 tool 消息还没入
    assert result.resume_messages[-1]["role"] == "assistant"
    assert result.resume_messages[-1]["tool_calls"][0]["id"] == "c1"
    assert all(message.get("role") != "tool" for message in result.resume_messages)


# ─────────────────────────────────────────────────────────────
# AgentCore：确认 / 取消 / 会话隔离
# ─────────────────────────────────────────────────────────────


class StubLoopExecutor:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []

    async def execute_batch(self, calls, **kwargs):
        self.calls.append({"calls": list(calls), **kwargs})
        return self.outcomes


class StubLoopRunner:
    def __init__(self, result, outcomes):
        self.result = result
        self.executor = StubLoopExecutor(outcomes)
        self.calls = []

    async def run_to_result(self, messages, tools=None, budget=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools, "budget": budget, **kwargs})
        return self.result


def _bare_agent(result=None, outcomes=None):
    agent = AgentCore.__new__(AgentCore)
    agent._loop_v2 = True
    agent.tool_executor = MagicMock()
    agent.tool_registry = MagicMock()
    agent.tool_registry.__len__ = MagicMock(return_value=0)
    agent._loop_budget = LoopBudget(max_steps=3)
    agent._loop_confirmations = ConfirmationStore(
        ttl_seconds=60, clock=lambda: 0.0
    )
    stub = StubLoopRunner(
        result or LoopResult(text="办好啦。", reason="stop"),
        outcomes or [ToolOutcome(call_id="c1", name="coding_delegate", ok=True, data={"done": True})],
    )
    agent._loop_runner = stub
    agent._clean_reply = MagicMock(side_effect=lambda text: (text or "").strip())
    agent._emotion_modulated_params = MagicMock(return_value={"temperature": 0.7, "max_tokens": 800})
    agent.context = AgentContext()
    agent._process_tool_side_effects = MagicMock()
    agent._write_conversation_log = AsyncMock()
    agent._schedule_memory_encoding = MagicMock()
    return agent, stub


def _seed_pending(agent, *, session: str = "web"):
    agent._loop_confirmations.put(
        "hezi",
        session,
        [_call("c1")],
        [{"role": "assistant", "content": "", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "coding_delegate", "arguments": '{"task": "rm"}'},
        }]}],
    )


@pytest.mark.asyncio
async def test_confirmation_executes_pending_and_continues():
    agent, stub = _bare_agent()
    _seed_pending(agent)
    trace_log = MagicMock()

    response = await agent._handle_loop_confirmation(_event("确认"), trace_log)

    assert response is not None
    assert response.reply == "办好啦。"
    assert len(stub.executor.calls) == 1
    assert stub.executor.calls[0]["calls"][0].id == "c1"
    # 续跑时上下文最后一条是 pending 的 tool 结果，然后才是模型继续
    resume_messages = stub.calls[0]["messages"]
    assert resume_messages[-1]["role"] == "tool"
    assert '"ok": true' in resume_messages[-1]["content"]
    # pending 已清除，历史落了两条
    assert agent._loop_confirmations.get("hezi", "web") is None
    assert [m["role"] for m in agent.context.history] == ["user", "assistant"]
    agent._process_tool_side_effects.assert_called_once()
    agent._write_conversation_log.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_confirm_text_cancels_pending():
    agent, stub = _bare_agent()
    _seed_pending(agent)

    response = await agent._handle_loop_confirmation(_event("算了不用了"), MagicMock())

    assert response is None
    assert agent._loop_confirmations.get("hezi", "web") is None
    assert stub.executor.calls == []


@pytest.mark.asyncio
async def test_confirmation_is_scoped_by_session():
    agent, stub = _bare_agent()
    _seed_pending(agent, session="web")

    # 另一个会话说「确认」不应执行 web 的 pending
    response = await agent._handle_loop_confirmation(
        _event("确认", session_id="console"), MagicMock()
    )

    assert response is None
    assert stub.executor.calls == []
    assert agent._loop_confirmations.get("hezi", "web") is not None
