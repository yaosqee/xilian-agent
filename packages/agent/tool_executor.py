"""
ToolExecutor — 工具执行调度器

统一入口：校验 → 权限 → 频率 → 确认 → 执行 → 审计。
打磨期：工具系统重设计核心组件。
"""
import asyncio
import json
import time
from typing import Optional
from loguru import logger

from .tool_registry import ToolRegistry, ToolPermission
from .tool_result import ToolResult, ToolContext


class ToolExecutor:
    """
    工具执行器 — 统一调度、权限校验、频率控制、审计日志。

    用法:
        executor = ToolExecutor(registry, db)
        result = await executor.execute("search_memory", {"query": "..."}, user_id="hezi")
    """

    def __init__(self, registry: ToolRegistry, db,
                 memory_manager=None, portrait_manager=None,
                 notebook_manager=None):
        self.registry = registry
        self.db = db
        self.memory = memory_manager
        self.portrait = portrait_manager
        self.notebook = notebook_manager
        self._call_counts: dict[str, list[float]] = {}  # tool_name → [timestamps]
        self._global_timeout: float = 60.0

    # ── 主入口 ──────────────────────────────────────────

    async def execute(self, tool_name: str, arguments: dict,
                      user_id: str = "", safe_mode: bool = False) -> ToolResult:
        """
        执行一个工具调用。

        流程: validate → permission → rate_limit → confirm → execute → audit_log
        """
        # 1. validate
        tool = self.registry.get_tool(tool_name)
        if not tool:
            logger.warning("tool_executor.not_found", tool=tool_name)
            return ToolResult.fail(f"人家好像还没学会「{tool_name}」这个技能呢……")

        # 2. permission
        if safe_mode and tool["permission"] != ToolPermission.READ_ONLY:
            logger.warning("tool_executor.blocked_safe_mode", tool=tool_name)
            return ToolResult.fail("人家现在在安全模式下，这个操作暂时不能做呢……")

        # 3. rate_limit
        if not self._check_rate_limit(tool_name):
            logger.warning("tool_executor.rate_limited", tool=tool_name)
            return ToolResult.fail("刚才已经帮你查过了呢……等一会儿再看好不好？")

        # 4. confirm — 如需确认，返回特殊结果由调用方处理
        if tool.get("requires_confirmation"):
            # 标记：需要调用方（agent_core）发起确认流程
            return ToolResult(
                success=False,
                error="PENDING_CONFIRMATION",
                data={"tool_name": tool_name, "arguments": arguments},
            )

        # 5. execute
        ctx = ToolContext(
            user_id=user_id,
            db=self.db,
            memory_manager=self.memory,
            portrait_manager=self.portrait,
            notebook_manager=self.notebook,
        )
        result = await self._execute_with_timeout(tool, arguments, ctx)

        # 6. Phase 4: 记录工具调用日志（fire-and-forget，不阻塞）──
        try:
            import json as _json
            args_str = _json.dumps(arguments, ensure_ascii=False)[:500] if arguments else ""
            await self.db.insert_tool_usage(
                tool_name=tool_name,
                arguments=args_str,
                success=result.success,
            )
        except Exception:
            pass  # 日志失败不影响工具执行

        # 7. audit_log
        await self._write_audit_log(tool_name, arguments, result, user_id)

        return result

    # ── 内部方法 ─────────────────────────────────────────

    def _check_rate_limit(self, tool_name: str) -> bool:
        """滑动窗口频率检查。"""
        tool = self.registry.get_tool(tool_name)
        max_freq = tool.get("max_frequency", 10) if tool else 10
        if max_freq == 0:
            return True

        now = time.time()
        window = 3600  # 1 小时窗口
        timestamps = self._call_counts.get(tool_name, [])
        # 清理过期记录
        timestamps = [t for t in timestamps if now - t < window]
        self._call_counts[tool_name] = timestamps

        if len(timestamps) >= max_freq:
            return False
        return True

    async def _execute_with_timeout(self, tool: dict, arguments: dict,
                                    ctx: ToolContext) -> ToolResult:
        """带超时的异步执行。"""
        tool_name = tool["name"]
        func = tool["func"]

        try:
            # 检查函数是否接受 ctx 参数
            import inspect
            sig = inspect.signature(func)
            call_args = dict(arguments)
            if "ctx" in sig.parameters:
                call_args["ctx"] = ctx

            result = await asyncio.wait_for(
                func(**call_args) if call_args else func(),
                timeout=self._global_timeout,
            )
            # 如果函数返回的是 ToolResult，直接使用；否则包装
            if isinstance(result, ToolResult):
                return result
            return ToolResult.ok(result)
        except asyncio.TimeoutError:
            logger.error("tool_executor.timeout", tool=tool_name)
            return ToolResult.fail("那边有点慢呢……人家没等到结果 (´•ω•̥`) 等会儿再试试好不好？")
        except Exception as e:
            logger.error("tool_executor.error", tool=tool_name, error=str(e))
            return ToolResult.fail(f"出了一点小问题……等会儿再试试好不好？")

    async def _write_audit_log(self, tool_name: str, arguments: dict,
                               result: ToolResult, user_id: str):
        """写入审计日志到 audit_logs 表。"""
        try:
            await self.db.insert_audit_log(
                event_type="tool_call",
                user_id=user_id,
                detail=json.dumps({
                    "tool": tool_name,
                    "arguments": arguments,
                    "success": result.success,
                    "error": result.error[:200] if result.error else "",
                }, ensure_ascii=False),
            )
        except Exception as e:
            logger.warning("tool_executor.audit_log_failed", error=str(e))

    async def _record_call(self, tool_name: str):
        """记录一次成功调用（频率统计）。"""
        now = time.time()
        if tool_name not in self._call_counts:
            self._call_counts[tool_name] = []
        self._call_counts[tool_name].append(now)

    # ── LLM 格式 ────────────────────────────────────────

    def to_llm_format(self) -> list[dict]:
        """将注册的工具转为 OpenAI function-calling 格式。"""
        return self.registry.to_openai_tools()
