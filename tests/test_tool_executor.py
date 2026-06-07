"""
test_tool_executor — ToolExecutor 单元测试

测试工具执行调度的核心路径：验证→权限→频率→确认→执行→记录。
所有外部依赖（DB、ToolRegistry）均 mock。
"""
import sys
sys.path.insert(0, ".")

import pytest
from unittest.mock import AsyncMock, MagicMock

from packages.agent.tool_executor import ToolExecutor
from packages.agent.tool_registry import ToolRegistry, ToolPermission
from packages.agent.tool_result import ToolResult


class TestToolExecutor:
    """ToolExecutor 单元测试。"""

    @pytest.fixture
    def registry(self):
        """创建一个含 2 个注册工具的 ToolRegistry。"""
        reg = ToolRegistry()
        # register() 是装饰器工厂: register(name, desc, schema)(func)
        reg.register("search_memory", "search tool", {}, permission=ToolPermission.READ_ONLY)(
            AsyncMock(return_value="found")
        )
        reg.register("dangerous_op", "dangerous tool", {}, permission=ToolPermission.EXECUTE,
                     requires_confirmation=True, max_frequency=2)(
            AsyncMock(return_value="done")
        )
        return reg

    @pytest.fixture
    def db(self):
        """Mock DatabaseManager。"""
        mock = MagicMock()
        mock.insert_tool_usage = AsyncMock()
        mock.insert_audit_log = AsyncMock()
        return mock

    @pytest.fixture
    def executor(self, registry, db):
        """创建 ToolExecutor 实例。"""
        return ToolExecutor(registry, db)

    # ── 1. 工具未注册 ──

    @pytest.mark.asyncio
    async def test_execute_not_found(self, executor):
        result = await executor.execute("nonexistent", {}, user_id="hezi")
        assert result.success is False
        assert "没学会" in result.error

    # ── 2. 安全模式 ──

    @pytest.mark.asyncio
    async def test_execute_blocked_in_safe_mode(self, executor):
        result = await executor.execute("dangerous_op", {}, user_id="hezi", safe_mode=True)
        assert result.success is False
        assert "安全模式" in result.error

    # ── 3. 频率限制 ──

    @pytest.mark.asyncio
    async def test_execute_rate_limited(self, executor):
        import time
        # 先填满频率计数（使用当前时间，确保不超过 1 小时过期）
        now = time.time()
        executor._call_counts["search_memory"] = [now - 10, now - 20, now - 30,
                                                    now - 40, now - 50, now - 60,
                                                    now - 70, now - 80, now - 90,
                                                    now - 100]  # 10 条 → 达到 max_frequency=10
        result = await executor.execute("search_memory", {}, user_id="hezi")
        assert result.success is False
        assert "等一会儿" in result.error

    # ── 4. 正常执行 ──

    @pytest.mark.asyncio
    async def test_execute_success(self, executor):
        result = await executor.execute("search_memory", {"query": "test"}, user_id="hezi")
        assert result.success is True
        assert result.data == "found"

    # ── 5. 确认回路 ──

    @pytest.mark.asyncio
    async def test_execute_requires_confirmation(self, executor):
        result = await executor.execute("dangerous_op", {"action": "delete"}, user_id="hezi")
        assert result.success is False
        assert result.error == "PENDING_CONFIRMATION"
        assert result.data["tool_name"] == "dangerous_op"

    # ── 6. 频率记录 ──

    def test_record_call_updates_counts(self, executor):
        executor._record_call("search_memory")
        assert "search_memory" in executor._call_counts
        assert len(executor._call_counts["search_memory"]) == 1

    def test_check_rate_limit_under_limit(self, executor):
        executor._call_counts["search_memory"] = []  # 空 → 未超限
        assert executor._check_rate_limit("search_memory") is True

    def test_check_rate_limit_over_limit(self, executor):
        import time
        # 10 条记录（max_frequency 默认 10）→ 达到上限
        executor._call_counts["search_memory"] = [time.time()] * 10
        assert executor._check_rate_limit("search_memory") is False
