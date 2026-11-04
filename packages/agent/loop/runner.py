"""
AgentLoopRunner — 预算式 Agent 循环（P0 骨架）。

与旧 `AgentCore._handle_tool_calls` 的区别：
1. **每一步都带 tools**，`tool_choice="auto"`，不再「回传时不带工具」；
2. **结构化回填**：工具结果以 `{"ok": true, "data": ...}` 形式进入 tool 消息，
   不再经过 ResultWrapper 的 LLM 改写；
3. **预算**：步数 / 总 token / 总耗时，任一触顶就优雅收尾；
4. **事件流**：tool_call / tool_result / done 可被传输层消费（P1 接 SSE）。

本模块只新增能力，`AgentCore.process()` 保持原样；等验证通过后再由上层切换。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

from loguru import logger

from .events import (
    DoneEvent,
    LoopEvent,
    ToolCall,
    ToolCallEvent,
    ToolOutcome,
    ToolResultEvent,
)
from .executor import LoopToolExecutor


# 预算触顶时的兜底话术（由上层决定是否替换成人格化文案）。
DEFAULT_BUDGET_TEXT = "人家查得有点久了……先跟伙伴说这些，好吗？"


@dataclass
class LoopBudget:
    """一次循环的预算。任一触顶即收尾。"""

    max_steps: int = 6
    max_tokens: int = 20_000
    max_seconds: float = 90.0
    tool_timeout: float = 60.0


@dataclass
class LoopResult:
    """`run_to_result()` 的聚合结果，方便不关心事件流的调用方使用。"""

    text: str = ""
    reason: str = "stop"
    steps: int = 0
    tool_calls: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    error: str = ""
    events: list[LoopEvent] = field(default_factory=list)
    # 所有实际执行过的工具结果（含幂等缓存命中），供 AgentCore 处理副作用
    tool_outcomes: list[ToolOutcome] = field(default_factory=list)


class AgentLoopRunner:
    """预算式循环。依赖注入 router 与工具执行器，便于用假 adapter 单测。

    Args:
        router: 任何实现 `async route(task_type, messages, tools=..., tool_choice=..., ...)`
                并返回 `ProviderResponse` 的对象（现有 ModelRouter 即满足）。
        executor: `LoopToolExecutor`，或任何有
                  `async execute_batch(calls, *, user_id, timeout, cache)` 的对象。
        task_type: 路由任务类型，默认 "chat"。
        user_id: 透传给工具执行器。
        clock: 时间源，默认 `time.monotonic`；单测可注入假时钟。
    """

    def __init__(
        self,
        router: Any,
        executor: LoopToolExecutor,
        *,
        task_type: str = "chat",
        user_id: str = "",
        clock: Callable[[], float] | None = None,
    ):
        self.router = router
        self.executor = executor
        self.task_type = task_type
        self.user_id = user_id
        self._clock = clock or time.monotonic

    # ── 主循环 ───────────────────────────────────────────

    async def run(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        budget: LoopBudget | None = None,
        *,
        temperature: float = 0.7,
        max_tokens: int = 800,
        user_id: str | None = None,
        first_tool_choice: str | dict | None = None,
    ) -> AsyncIterator[LoopEvent]:
        """执行循环，逐事件产出。

        `messages` 不会被原地修改（浅拷贝后使用）。

        Args:
            user_id: 本次运行的工具执行用户；None 用 runner 构造时的默认值。
            first_tool_choice: 仅第一步使用的 tool_choice（快路径强制工具用）；
                None 表示第一步也用 "auto"。后续步始终 "auto"。
        """
        budget = budget or LoopBudget()
        max_steps = max(1, int(budget.max_steps))
        deadline = self._clock() + float(budget.max_seconds)
        run_user_id = self.user_id if user_id is None else user_id

        conversation = [self._copy_message(message) for message in messages]
        cache: dict[str, ToolOutcome] = {}
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        steps = 0
        tool_call_count = 0
        reason = "max_steps"
        text = DEFAULT_BUDGET_TEXT
        error = ""

        for step in range(1, max_steps + 1):
            steps = step

            if self._clock() >= deadline:
                reason = "budget_time"
                text = DEFAULT_BUDGET_TEXT
                break

            # 第一步允许快路径强制工具；后续步始终交还模型。
            if not tools:
                step_tool_choice = None
            elif step == 1 and first_tool_choice is not None:
                step_tool_choice = first_tool_choice
            else:
                step_tool_choice = "auto"

            try:
                response = await self.router.route(
                    self.task_type,
                    conversation,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=False,
                    # ★ 约束：每一步都带 tools，选择权交还模型。
                    tools=tools or None,
                    tool_choice=step_tool_choice,
                )
            except Exception as exc:  # noqa: BLE001 — 循环要把模型异常变成事件
                error = f"{type(exc).__name__}: {exc}"
                reason = "error"
                text = ""
                logger.warning("loop.runner.model_error", step=step, error=error[:300])
                break

            self._merge_usage(usage, getattr(response, "usage", None))
            calls = [
                ToolCall.from_raw(raw, index=index)
                for index, raw in enumerate(getattr(response, "tool_calls", None) or [])
            ]

            # 没有工具调用 → 本轮到终态。
            if not calls:
                content = getattr(response, "content", "") or ""
                if content.strip():
                    reason = "stop"
                    text = content.strip()
                else:
                    # 空回复不伪装，交给上层决定降级话术。
                    reason = "empty"
                    text = ""
                break

            # 有工具调用，但预算已触顶 → 不再执行，优雅收尾。
            if usage["total_tokens"] >= budget.max_tokens:
                reason = "budget_tokens"
                text = DEFAULT_BUDGET_TEXT
                logger.info(
                    "loop.runner.budget_tokens", step=step,
                    tokens=usage["total_tokens"], budget=budget.max_tokens,
                )
                break
            if self._clock() >= deadline:
                reason = "budget_time"
                text = DEFAULT_BUDGET_TEXT
                logger.info("loop.runner.budget_time", step=step, seconds=budget.max_seconds)
                break

            tool_call_count += len(calls)
            yield ToolCallEvent(step=step, calls=calls)

            outcomes = await self.executor.execute_batch(
                calls,
                user_id=run_user_id,
                timeout=budget.tool_timeout,
                cache=cache,
            )
            yield ToolResultEvent(step=step, results=outcomes)

            if any(outcome.needs_confirmation for outcome in outcomes):
                # P2 才接确认状态机；这里先把循环停在可恢复的位置。
                reason = "confirmation"
                text = ""
                break

            conversation.append(self._assistant_message(response, calls))
            conversation.extend(self._tool_messages(outcomes))

            if usage["total_tokens"] >= budget.max_tokens:
                reason = "budget_tokens"
                text = DEFAULT_BUDGET_TEXT
                logger.info(
                    "loop.runner.budget_tokens", step=step,
                    tokens=usage["total_tokens"], budget=budget.max_tokens,
                )
                break
            if self._clock() >= deadline:
                reason = "budget_time"
                text = DEFAULT_BUDGET_TEXT
                logger.info("loop.runner.budget_time", step=step, seconds=budget.max_seconds)
                break
        else:
            # for 正常走完 = 步数预算耗尽。
            reason = "max_steps"
            text = DEFAULT_BUDGET_TEXT
            logger.info("loop.runner.max_steps", limit=max_steps)

        logger.debug(
            "loop.runner.done", reason=reason, steps=steps,
            tool_calls=tool_call_count, tokens=usage["total_tokens"],
        )
        yield DoneEvent(
            text=text,
            reason=reason,
            steps=steps,
            tool_calls=tool_call_count,
            usage=self._finalize_usage(usage),
            error=error,
        )

    async def run_to_result(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        budget: LoopBudget | None = None,
        *,
        on_event: Callable[[LoopEvent], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> LoopResult:
        """消费事件流并聚合成 `LoopResult`（给暂时不需要事件的调用方）。

        Args:
            on_event: 可选异步回调；每个事件产出后调用一次，用于 SSE 实时转发。
                回调异常只记日志，不打断循环。
        """
        result = LoopResult()
        async for event in self.run(messages, tools, budget, **kwargs):
            result.events.append(event)
            if isinstance(event, ToolResultEvent):
                result.tool_outcomes.extend(event.results)
            elif isinstance(event, DoneEvent):
                result.text = event.text
                result.reason = event.reason
                result.steps = event.steps
                result.tool_calls = event.tool_calls
                result.usage = event.usage
                result.error = event.error
            if on_event is not None:
                try:
                    await on_event(event)
                except Exception as exc:  # noqa: BLE001 — 事件消费失败不能影响主循环
                    logger.warning(
                        "loop.runner.event_sink_error",
                        error_type=type(exc).__name__,
                        error=str(exc)[:200],
                    )
        return result

    # ── 消息构造 ─────────────────────────────────────────

    @staticmethod
    def _copy_message(message: dict) -> dict:
        """浅拷贝，避免循环往调用方的 messages 里追加内容。"""
        return dict(message) if isinstance(message, dict) else message

    @staticmethod
    def _assistant_message(response: Any, calls: list[ToolCall]) -> dict:
        """保留 tool_calls 与 reasoning_content，保证多步上下文一致。"""
        message: dict[str, Any] = {
            "role": "assistant",
            "content": getattr(response, "content", None) or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        # 原样写回模型给的参数串（即便不合法，也要让模型看到自己发了什么）。
                        "arguments": call.raw_arguments or "{}",
                    },
                }
                for call in calls
            ],
        }
        reasoning = getattr(response, "reasoning_content", None)
        if reasoning:
            message["reasoning_content"] = reasoning
        return message

    @staticmethod
    def _tool_messages(outcomes: list[ToolOutcome]) -> list[dict]:
        """结构化结果回填：一条 tool 消息对应一个 tool_call_id。"""
        return [
            {
                "role": "tool",
                "tool_call_id": outcome.call_id,
                "content": outcome.content(),
            }
            for outcome in outcomes
        ]

    # ── usage ────────────────────────────────────────────

    @staticmethod
    def _merge_usage(total: dict[str, int], usage: Any) -> None:
        if not isinstance(usage, dict):
            return

        def _as_int(value: Any) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        prompt = _as_int(usage.get("prompt_tokens"))
        completion = _as_int(usage.get("completion_tokens"))
        # 有的适配器只回 prompt/completion；预算判断不能因此永远看到 0。
        total_tokens = _as_int(usage.get("total_tokens")) or (prompt + completion)
        total["prompt_tokens"] += prompt
        total["completion_tokens"] += completion
        total["total_tokens"] += total_tokens

    @staticmethod
    def _finalize_usage(total: dict[str, int]) -> dict[str, int]:
        # 有的适配器只回 prompt/completion，这里补齐 total。
        if total["total_tokens"] == 0:
            total["total_tokens"] = total["prompt_tokens"] + total["completion_tokens"]
        return dict(total)
