"""
test_loop_runner — Agent 循环 v2（P0）离线单测。

覆盖方案要求的五个场景：多步 / 工具失败 / 超预算 / 幂等 / 空回复，
外加并行超时隔离、确认暂停、模型异常与事件序列化。
全部使用假 adapter（FakeRouter）与假工具执行器，不连网、不写库。
"""
import asyncio
import copy
import inspect
import json
import sys
import time

import pytest

sys.path.insert(0, ".")

from packages.agent.loop import (
    DEFAULT_BUDGET_TEXT,
    AgentLoopRunner,
    DoneEvent,
    LoopBudget,
    LoopToolExecutor,
    ToolCall,
    ToolCallEvent,
    ToolResultEvent,
)
from packages.agent.tool_result import ToolResult
from packages.shared.providers import ProviderResponse


# ─────────────────────────────────────────────────────────────
# 测试替身
# ─────────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_weather",
            "description": "查询城市天气",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "搜索网页",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]


def tool_call(name: str, arguments: dict, call_id: str) -> dict:
    """构造 OpenAI 格式的 tool_call。"""
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        },
    }


def make_response(
    *,
    content: str | None = None,
    tool_calls: list[dict] | None = None,
    usage: dict | None = None,
) -> ProviderResponse:
    return ProviderResponse(
        content=content,
        tool_calls=tool_calls,
        model="fake-flash",
        usage=usage,
        finish_reason="tool_calls" if tool_calls else "stop",
    )


class FakeRouter:
    """按脚本返回响应，并记录每次调用的完整参数。"""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def route(self, task_type: str, messages: list, **kwargs):
        self.calls.append(
            {
                "task_type": task_type,
                "messages": copy.deepcopy(messages),
                **kwargs,
            }
        )
        if not self._responses:
            raise AssertionError("FakeRouter 收到了脚本外的模型调用")
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class SlowRouter(FakeRouter):
    """每次模型调用先睡一会儿，用于测时间预算。"""

    def __init__(self, responses: list, delay: float = 0.02):
        super().__init__(responses)
        self.delay = delay

    async def route(self, task_type: str, messages: list, **kwargs):
        await asyncio.sleep(self.delay)
        return await super().route(task_type, messages, **kwargs)


class FakeToolExecutor:
    """实现旧 ToolExecutor 的 execute() 形状，按工具名分派。"""

    def __init__(self, handlers: dict | None = None):
        self.handlers = dict(handlers or {})
        self.calls: list[dict] = []

    async def execute(self, name: str, arguments: dict, user_id: str = "") -> ToolResult:
        self.calls.append({"name": name, "arguments": dict(arguments), "user_id": user_id})
        handler = self.handlers.get(name)
        if handler is None:
            return ToolResult.ok({"echo": arguments})
        if isinstance(handler, BaseException):
            raise handler
        value = handler(name, arguments) if callable(handler) else handler
        if inspect.isawaitable(value):
            value = await value
        return value


async def collect_events(
    runner: AgentLoopRunner,
    messages: list[dict],
    tools: list[dict] | None = TOOLS,
    budget: LoopBudget | None = None,
) -> list:
    events = []
    async for event in runner.run(messages, tools, budget):
        events.append(event)
    return events


# ─────────────────────────────────────────────────────────────
# 1. 多步循环：每步都带 tools + 结构化回填
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_step_keeps_tools_and_structured_backfill():
    router = FakeRouter(
        [
            make_response(
                tool_calls=[tool_call("query_weather", {"city": "杭州"}, "c1")],
                usage={"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            ),
            make_response(
                tool_calls=[tool_call("search_web", {"query": "杭州 天气"}, "c2")],
                usage={"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
            ),
            make_response(
                content="杭州今天 18～24℃，多云。",
                usage={"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
            ),
        ]
    )
    tools = FakeToolExecutor(
        {
            "query_weather": ToolResult.ok(
                {"city": "杭州", "temp": "18-24℃", "weather": "多云"}
            ),
            "search_web": ToolResult.ok({"results": ["杭州天气预报"]}),
        }
    )
    runner = AgentLoopRunner(router, LoopToolExecutor(tools), user_id="hezi")
    original = [{"role": "user", "content": "查下杭州天气，再搜一下"}]

    events = await collect_events(runner, original, budget=LoopBudget(max_steps=5))

    assert [event.type for event in events] == [
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "done",
    ]
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.reason == "stop"
    assert done.steps == 3
    assert done.tool_calls == 2
    assert "18" in done.text
    assert done.usage == {"prompt_tokens": 18, "completion_tokens": 12, "total_tokens": 30}

    # ★ 每一步（含工具回传后的后续步）都必须带 tools + auto
    assert len(router.calls) == 3
    for call in router.calls:
        assert call["tools"] == TOOLS
        assert call["tool_choice"] == "auto"

    # 第二步上下文：assistant(tool_calls) + 一条结构化 tool 消息
    second_messages = router.calls[1]["messages"]
    assistant = next(m for m in second_messages if m["role"] == "assistant")
    assert assistant["tool_calls"][0]["id"] == "c1"
    tool_message = next(m for m in second_messages if m["role"] == "tool")
    assert tool_message["tool_call_id"] == "c1"
    payload = json.loads(tool_message["content"])
    assert payload == {
        "ok": True,
        "data": {"city": "杭州", "temp": "18-24℃", "weather": "多云"},
    }

    # 不原地修改调用方的 messages
    assert original == [{"role": "user", "content": "查下杭州天气，再搜一下"}]


# ─────────────────────────────────────────────────────────────
# 2. 工具失败：不抛异常，结构化告知模型
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_failure_becomes_structured_result():
    router = FakeRouter(
        [
            make_response(tool_calls=[tool_call("query_weather", {"city": "杭州"}, "c1")]),
            make_response(content="人家没查到杭州的天气呢……"),
        ]
    )
    tools = FakeToolExecutor({"query_weather": RuntimeError("network down")})
    runner = AgentLoopRunner(router, LoopToolExecutor(tools))

    events = await collect_events(runner, [{"role": "user", "content": "杭州天气？"}])

    result_event = events[1]
    assert isinstance(result_event, ToolResultEvent)
    outcome = result_event.results[0]
    assert outcome.ok is False
    assert "network down" in outcome.error
    assert "RuntimeError" in outcome.error

    # 回填给模型的是 JSON 错误对象，而不是异常或空串
    tool_message = router.calls[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    payload = json.loads(tool_message["content"])
    assert payload["ok"] is False
    assert "network down" in payload["error"]
    assert "data" not in payload

    assert events[-1].reason == "stop"
    assert "没查到" in events[-1].text


@pytest.mark.asyncio
async def test_invalid_arguments_never_reach_tool():
    executor = LoopToolExecutor(FakeToolExecutor())
    call = ToolCall.from_raw(
        {
            "id": "c1",
            "type": "function",
            "function": {"name": "query_weather", "arguments": "{not json"},
        }
    )
    cache: dict = {}
    outcomes = await executor.execute_batch([call], cache=cache)

    assert call.argument_error
    assert outcomes[0].ok is False
    assert "不是合法 JSON" in outcomes[0].error
    assert executor.tool_executor.calls == []

    # 坏参数的失败不能污染同一工具后续的合法调用（缓存 key 不同）
    valid_call = ToolCall.from_raw(tool_call("query_weather", {}, "c2"))
    valid_outcomes = await executor.execute_batch([valid_call], cache=cache)
    assert valid_outcomes[0].ok is True
    assert len(executor.tool_executor.calls) == 1


# ─────────────────────────────────────────────────────────────
# 3. 幂等：同工具 + 同参数复用
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotent_across_steps_and_within_batch():
    same_args = {"city": "杭州"}
    router = FakeRouter(
        [
            make_response(tool_calls=[tool_call("query_weather", same_args, "c1")]),
            make_response(tool_calls=[tool_call("query_weather", same_args, "c2")]),
            make_response(content="刚查过啦，杭州 18℃。"),
        ]
    )
    tools = FakeToolExecutor({"query_weather": ToolResult.ok({"temp": 18})})
    runner = AgentLoopRunner(router, LoopToolExecutor(tools))

    events = await collect_events(
        runner, [{"role": "user", "content": "再查一次杭州"}]
    )

    # 底层只真正执行一次
    assert len(tools.calls) == 1
    first, second = events[1].results[0], events[3].results[0]
    assert first.cached is False
    assert second.cached is True
    assert second.call_id == "c2"  # 结果复用，但 call_id 仍对应当前调用

    payload = json.loads(router.calls[2]["messages"][-1]["content"])
    assert payload["ok"] is True
    assert payload["cached"] is True

    # 同一批里的重复调用也只执行一次
    batch_executor = LoopToolExecutor(FakeToolExecutor())
    calls = [
        ToolCall.from_raw(tool_call("query_weather", same_args, "b1")),
        ToolCall.from_raw(tool_call("query_weather", same_args, "b2")),
    ]
    outcomes = await batch_executor.execute_batch(calls, cache={})
    assert len(batch_executor.tool_executor.calls) == 1
    assert [o.cached for o in outcomes] == [False, True]


# ─────────────────────────────────────────────────────────────
# 4. 预算：步数 / token / 时间
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_max_steps_budget():
    responses = [
        make_response(tool_calls=[tool_call("query_weather", {"city": f"城市{i}"}, f"c{i}")])
        for i in range(5)
    ]
    router = FakeRouter(responses)
    tools = FakeToolExecutor()
    runner = AgentLoopRunner(router, LoopToolExecutor(tools))

    result = await runner.run_to_result(
        [{"role": "user", "content": "一直查"}],
        TOOLS,
        LoopBudget(max_steps=2, max_seconds=30),
    )

    assert result.reason == "max_steps"
    assert result.steps == 2
    assert result.tool_calls == 2
    assert result.text == DEFAULT_BUDGET_TEXT
    assert len(router.calls) == 2
    assert len(tools.calls) == 2
    assert result.events[-1].type == "done"


@pytest.mark.asyncio
async def test_token_budget_stops_before_tool_execution():
    router = FakeRouter(
        [
            make_response(
                tool_calls=[tool_call("query_weather", {"city": "杭州"}, "c1")],
                # 只回 prompt/completion，验证预算不依赖 total_tokens 字段
                usage={"prompt_tokens": 60, "completion_tokens": 40},
            )
        ]
    )
    tools = FakeToolExecutor()
    runner = AgentLoopRunner(router, LoopToolExecutor(tools))

    result = await runner.run_to_result(
        [{"role": "user", "content": "杭州天气"}],
        TOOLS,
        LoopBudget(max_steps=5, max_tokens=50),
    )

    assert result.reason == "budget_tokens"
    assert result.steps == 1
    assert result.tool_calls == 0
    assert result.text == DEFAULT_BUDGET_TEXT
    assert result.usage["total_tokens"] == 100
    assert tools.calls == []  # 预算已满，不再执行工具
    assert [event.type for event in result.events] == ["done"]


@pytest.mark.asyncio
async def test_time_budget_stops_loop():
    router = SlowRouter(
        [make_response(tool_calls=[tool_call("query_weather", {"city": "杭州"}, "c1")])],
        delay=0.02,
    )
    tools = FakeToolExecutor()
    runner = AgentLoopRunner(router, LoopToolExecutor(tools))

    result = await runner.run_to_result(
        [{"role": "user", "content": "杭州天气"}],
        TOOLS,
        LoopBudget(max_steps=5, max_seconds=0.001),
    )

    assert result.reason == "budget_time"
    assert result.steps == 1
    assert result.tool_calls == 0
    assert result.text == DEFAULT_BUDGET_TEXT
    assert len(router.calls) == 1
    assert tools.calls == []


# ─────────────────────────────────────────────────────────────
# 5. 空回复 / 模型异常 / 确认暂停
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_reply_is_explicit():
    router = FakeRouter([make_response(content="", usage={"total_tokens": 3})])
    runner = AgentLoopRunner(router, LoopToolExecutor(FakeToolExecutor()))

    result = await runner.run_to_result([{"role": "user", "content": "在吗"}], TOOLS)

    assert result.reason == "empty"
    assert result.text == ""
    assert result.steps == 1
    assert [event.type for event in result.events] == ["done"]


@pytest.mark.asyncio
async def test_model_error_becomes_done_event():
    router = FakeRouter([RuntimeError("rate limited")])
    runner = AgentLoopRunner(router, LoopToolExecutor(FakeToolExecutor()))

    result = await runner.run_to_result([{"role": "user", "content": "在吗"}], TOOLS)

    assert result.reason == "error"
    assert result.text == ""
    assert "rate limited" in result.error


@pytest.mark.asyncio
async def test_confirmation_pauses_loop():
    router = FakeRouter(
        [make_response(tool_calls=[tool_call("coding_delegate", {"task": "rm"}, "c1")])]
    )
    tools = FakeToolExecutor(
        {
            "coding_delegate": ToolResult(
                success=False,
                error="PENDING_CONFIRMATION",
                data={"tool_name": "coding_delegate", "arguments": {"task": "rm"}},
            )
        }
    )
    runner = AgentLoopRunner(router, LoopToolExecutor(tools))

    result = await runner.run_to_result(
        [{"role": "user", "content": "帮我删个东西"}], TOOLS
    )

    assert result.reason == "confirmation"
    assert result.text == ""
    assert len(router.calls) == 1  # 不再继续请求模型
    outcome = result.events[1].results[0]
    assert outcome.needs_confirmation is True
    assert json.loads(outcome.content())["needs_confirmation"] is True


# ─────────────────────────────────────────────────────────────
# 6. 执行器：并行 + 单工具超时隔离
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_tool_timeout_does_not_affect_others():
    async def slow_tool(name, arguments):
        await asyncio.sleep(1.0)
        return ToolResult.ok({"slow": True})

    tools = FakeToolExecutor(
        {"slow_tool": slow_tool, "search_web": ToolResult.ok({"results": ["ok"]})}
    )
    executor = LoopToolExecutor(tools, timeout=0.05)
    calls = [
        ToolCall.from_raw(tool_call("slow_tool", {}, "c1")),
        ToolCall.from_raw(tool_call("search_web", {"query": "x"}, "c2")),
    ]

    started = time.monotonic()
    outcomes = await executor.execute_batch(calls, cache={})
    elapsed = time.monotonic() - started

    assert outcomes[0].ok is False
    assert "超时" in outcomes[0].error
    assert outcomes[1].ok is True
    assert outcomes[1].data == {"results": ["ok"]}
    assert elapsed < 0.5  # 慢工具被超时截断，且两个工具并行


# ─────────────────────────────────────────────────────────────
# 7. 事件序列化（为 P1 SSE 预留）
# ─────────────────────────────────────────────────────────────


def test_events_are_json_and_sse_serializable():
    call = ToolCall.from_raw(tool_call("query_weather", {"city": "杭州"}, "c1"))
    call_event = ToolCallEvent(step=1, calls=[call])
    payload = call_event.to_dict()
    assert payload["type"] == "tool_call"
    assert payload["calls"][0]["name"] == "query_weather"
    json.dumps(payload, ensure_ascii=False)

    sse = DoneEvent(text="好", reason="stop", steps=1).to_sse()
    assert sse.startswith("event: done\n")
    body = json.loads(sse.split("data: ", 1)[1].strip())
    assert body == {
        "text": "好",
        "reason": "stop",
        "steps": 1,
        "tool_calls": 0,
        "usage": {},
        "error": "",
        "type": "done",
    }
