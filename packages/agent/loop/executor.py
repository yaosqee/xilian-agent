"""
LoopToolExecutor — 新循环的工具批执行器。

职责（对应 `docs/plans/agent-loop-v2.md` §2.2）：
1. 同一轮多个 tool_calls 并行执行；
2. 单个工具超时/异常不影响同批其他工具，统一归一成 `ToolOutcome`；
3. 幂等：同工具 + 同参数在「本轮」内复用结果，第二次起标记 `cached=True`；
4. 不抛异常给循环：模型需要看到可解释的失败，而不是整轮崩掉。

它包装现有的 `packages.agent.tool_executor.ToolExecutor`（或任何实现
`async execute(name, arguments, user_id=...) -> ToolResult` 的对象），
不改动旧执行器，也不切换旧调用路径。
"""
from __future__ import annotations

import asyncio
import inspect
import json
import time
from dataclasses import replace
from typing import Any, Iterable, MutableMapping

from loguru import logger

from .events import ToolCall, ToolOutcome


class LoopToolExecutor:
    """并行执行一批工具调用，并维护本轮幂等缓存。

    用法::

        executor = LoopToolExecutor(tool_executor, timeout=60, max_parallel=8)
        cache: dict[str, ToolOutcome] = {}      # 每次 runner.run() 新建
        outcomes = await executor.execute_batch(calls, user_id="hezi", cache=cache)
    """

    def __init__(self, executor: Any, *, timeout: float = 60.0, max_parallel: int = 8):
        self._executor = executor
        self.timeout = float(timeout)
        self.max_parallel = max(1, int(max_parallel))
        # 底层执行器是否支持 confirmed 参数（ToolExecutor 支持；单测桩可能不支持）
        self._accepts_confirmed = self._supports_confirmed(executor)

    @staticmethod
    def _supports_confirmed(executor: Any) -> bool:
        try:
            return "confirmed" in inspect.signature(executor.execute).parameters
        except (TypeError, ValueError, AttributeError):
            return False

    @property
    def tool_executor(self) -> Any:
        return self._executor

    # ── 幂等 key ─────────────────────────────────────────

    @staticmethod
    def cache_key(call: ToolCall) -> str:
        """同工具 + 同参数 -> 同一个 key。参数按键排序，避免顺序差异。"""
        if call.argument_error:
            # 参数解析失败的调用不能和「合法的空参数调用」共用缓存，
            # 否则一次坏参数会把后续正常重试也判成失败。
            return f"{call.name}\x1f!invalid\x1f{call.raw_arguments}"
        try:
            args = json.dumps(
                call.arguments or {}, sort_keys=True, ensure_ascii=False, default=str
            )
        except (TypeError, ValueError):
            args = str(call.arguments)
        return f"{call.name}\x1f{args}"

    # ── 批执行 ───────────────────────────────────────────

    async def execute_batch(
        self,
        calls: Iterable[ToolCall],
        *,
        user_id: str = "",
        timeout: float | None = None,
        cache: MutableMapping[str, ToolOutcome] | None = None,
        confirmed: bool = False,
    ) -> list[ToolOutcome]:
        """并行执行 calls，返回与输入顺序一一对应的结果。

        Args:
            calls: 本步的工具调用（已归一化）。
            user_id: 透传给旧执行器的用户标识。
            timeout: 单工具超时秒数；None 用构造时的默认值。
            cache: 本轮幂等缓存（runner 持有，每轮新建）。None 时临时新建，
                   调用方拿不到跨步复用，建议显式传入。
            confirmed: 用户已确认（确认回路重放时传 True），底层会跳过
                   requires_confirmation 的 PENDING 短路。
        """
        calls = list(calls)
        if not calls:
            return []

        call_timeout = self.timeout if timeout is None else float(timeout)
        cache = cache if cache is not None else {}

        keys = [self.cache_key(call) for call in calls]

        # 先把「缓存里没有」的 key 去重，保证同一批里的重复调用也只执行一次。
        pending: dict[str, ToolCall] = {}
        first_index: dict[str, int] = {}
        for index, (key, call) in enumerate(zip(keys, calls)):
            if key in cache or key in pending:
                continue
            pending[key] = call
            first_index[key] = index

        if pending:
            semaphore = asyncio.Semaphore(self.max_parallel)

            async def run_one(call: ToolCall) -> ToolOutcome:
                async with semaphore:
                    return await self._execute_one(
                        call, user_id=user_id, timeout=call_timeout, confirmed=confirmed
                    )

            fetched = await asyncio.gather(
                *(run_one(call) for call in pending.values()),
                return_exceptions=True,
            )
            for key, call, result in zip(pending.keys(), pending.values(), fetched):
                if isinstance(result, asyncio.CancelledError):
                    # 取消要向上传播，不能伪装成工具失败。
                    raise result
                if isinstance(result, BaseException):
                    result = self._exception_outcome(call, result)
                cache[key] = result

        outcomes: list[ToolOutcome] = []
        for index, (key, call) in enumerate(zip(keys, calls)):
            template = cache[key]
            is_origin = first_index.get(key) == index
            outcomes.append(
                replace(
                    template,
                    call_id=call.id,
                    name=call.name,
                    arguments=call.arguments,
                    cached=not is_origin,
                )
            )
        return outcomes

    # ── 单工具执行 ───────────────────────────────────────

    async def _execute_one(self, call: ToolCall, *, user_id: str, timeout: float,
                           confirmed: bool = False) -> ToolOutcome:
        started = time.monotonic()

        def _fail(message: str) -> ToolOutcome:
            return ToolOutcome(
                call_id=call.id,
                name=call.name,
                arguments=call.arguments,
                ok=False,
                error=message,
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        if call.argument_error:
            return _fail(call.argument_error)
        if not call.name:
            return _fail("模型返回了空的工具名，未执行")

        try:
            call_kwargs: dict[str, Any] = {"user_id": user_id}
            if confirmed and self._accepts_confirmed:
                call_kwargs["confirmed"] = True
            result = await asyncio.wait_for(
                self._executor.execute(
                    call.name, dict(call.arguments or {}), **call_kwargs
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "loop.executor.timeout", tool=call.name, timeout=timeout,
                args=str(call.arguments)[:120],
            )
            return _fail(f"工具「{call.name}」执行超时（{timeout:g} 秒）")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — 单工具异常必须归一，不能打断循环
            logger.warning(
                "loop.executor.error", tool=call.name, error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
            return _fail(f"工具「{call.name}」执行失败：{type(exc).__name__}: {exc}")

        ok = bool(getattr(result, "success", False))
        error = str(getattr(result, "error", "") or "")
        return ToolOutcome(
            call_id=call.id,
            name=call.name,
            arguments=call.arguments,
            ok=ok,
            data=getattr(result, "data", None),
            error=error,
            duration_ms=int((time.monotonic() - started) * 1000),
            needs_confirmation=(not ok and error == "PENDING_CONFIRMATION"),
            trigger_memory=bool(getattr(result, "trigger_memory", False)),
            trigger_portrait_update=bool(getattr(result, "trigger_portrait_update", False)),
        )

    @staticmethod
    def _exception_outcome(call: ToolCall, exc: BaseException) -> ToolOutcome:
        logger.warning(
            "loop.executor.unexpected", tool=call.name,
            error_type=type(exc).__name__, error=str(exc)[:200],
        )
        return ToolOutcome(
            call_id=call.id,
            name=call.name,
            arguments=call.arguments,
            ok=False,
            error=f"工具「{call.name}」执行异常：{type(exc).__name__}: {exc}",
        )
